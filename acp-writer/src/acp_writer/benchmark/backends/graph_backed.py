"""Graph-backed benchmark backend — FHIR→NetworkX projection for query traversal.

Projects IPS resources, references, and temporal relationships into
an in-process NetworkX graph. Implements the same extraction primitives
as the current backend but via graph traversal.

No external graph database or query engine — pure in-process NetworkX.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import mlflow

from acp_writer.benchmark.models import QAAnswer
from acp_writer.tools.concept_resolver import resolve as resolve_concept
from acp_writer.tools.ips_extractor import _get_effective_date, _get_resources

logger = logging.getLogger(__name__)

try:
    import networkx as nx
except ImportError:
    nx = None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None


def build_fhir_graph(bundle: dict) -> "nx.DiGraph":
    """Project a FHIR IPS bundle into a NetworkX directed graph."""
    if nx is None:
        raise ImportError("networkx is required for the graph-backed backend")

    G = nx.DiGraph()

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        rt = resource.get("resourceType", "")
        rid = resource.get("id", "unknown")
        node_id = f"{rt}/{rid}"

        node_attrs = {
            "resourceType": rt,
            "fhir_id": rid,
        }

        if rt == "Patient":
            node_attrs["birthDate"] = resource.get("birthDate")
            node_attrs["gender"] = resource.get("gender")
            names = resource.get("name", [])
            if names:
                node_attrs["name"] = f"{' '.join(names[0].get('given', []))} {names[0].get('family', '')}".strip()

        elif rt == "Condition":
            for coding in resource.get("code", {}).get("coding", []):
                node_attrs.setdefault("codes", []).append(f"{coding.get('system', '')}|{coding.get('code', '')}")
                node_attrs["display"] = coding.get("display", "")
            status_codings = resource.get("clinicalStatus", {}).get("coding", [])
            node_attrs["clinicalStatus"] = status_codings[0].get("code", "unknown") if status_codings else "unknown"
            node_attrs["onset"] = resource.get("onsetDateTime")

        elif rt == "Observation":
            for coding in resource.get("code", {}).get("coding", []):
                node_attrs.setdefault("codes", []).append(f"{coding.get('system', '')}|{coding.get('code', '')}")
                node_attrs["display"] = coding.get("display", "")
            node_attrs["effectiveDateTime"] = _get_effective_date(resource)
            node_attrs["effective_dt"] = _parse_dt(node_attrs["effectiveDateTime"])

            vq = resource.get("valueQuantity")
            if vq and vq.get("value") is not None:
                node_attrs["value"] = vq["value"]
                node_attrs["unit"] = vq.get("unit")

            vcc = resource.get("valueCodeableConcept")
            if vcc:
                codings = vcc.get("coding", [])
                node_attrs["value"] = codings[0].get("code") if codings else vcc.get("text")

            if resource.get("valueString") is not None:
                node_attrs["value"] = resource["valueString"]
            if resource.get("valueBoolean") is not None:
                node_attrs["value"] = resource["valueBoolean"]

            for comp in resource.get("component", []):
                for coding in comp.get("code", {}).get("coding", []):
                    comp_code = f"{coding.get('system', '')}|{coding.get('code', '')}"
                    comp_vq = comp.get("valueQuantity", {})
                    if comp_vq.get("value") is not None:
                        node_attrs.setdefault("components", {})[comp_code] = {
                            "value": comp_vq["value"],
                            "unit": comp_vq.get("unit"),
                            "display": coding.get("display", ""),
                        }

        elif rt in ("MedicationStatement", "MedicationRequest"):
            node_attrs["status"] = resource.get("status", "unknown")
            for coding in resource.get("medicationCodeableConcept", {}).get("coding", []):
                node_attrs.setdefault("codes", []).append(f"{coding.get('system', '')}|{coding.get('code', '')}")
                node_attrs["display"] = coding.get("display", "")
            start = resource.get("authoredOn") or resource.get("effectiveDateTime")
            node_attrs["startDate"] = start
            node_attrs["start_dt"] = _parse_dt(start)

        elif rt == "AllergyIntolerance":
            for coding in resource.get("code", {}).get("coding", []):
                node_attrs.setdefault("codes", []).append(f"{coding.get('system', '')}|{coding.get('code', '')}")
                node_attrs["display"] = coding.get("display", "")
            node_attrs["criticality"] = resource.get("criticality")
            status_codings = resource.get("clinicalStatus", {}).get("coding", [])
            node_attrs["clinicalStatus"] = status_codings[0].get("code", "unknown") if status_codings else "unknown"

        elif rt == "Encounter":
            node_attrs["period_start"] = resource.get("period", {}).get("start")
            node_attrs["period_start_dt"] = _parse_dt(node_attrs["period_start"])
            node_attrs["class"] = resource.get("class", {}).get("code", "")

        elif rt == "DiagnosticReport":
            for coding in resource.get("code", {}).get("coding", []):
                node_attrs.setdefault("codes", []).append(f"{coding.get('system', '')}|{coding.get('code', '')}")
                node_attrs["display"] = coding.get("display", "")
            node_attrs["effectiveDateTime"] = resource.get("effectiveDateTime")
            node_attrs["effective_dt"] = _parse_dt(node_attrs["effectiveDateTime"])
            node_attrs["status"] = resource.get("status", "unknown")

        elif rt == "Procedure":
            for coding in resource.get("code", {}).get("coding", []):
                node_attrs.setdefault("codes", []).append(f"{coding.get('system', '')}|{coding.get('code', '')}")
                node_attrs["display"] = coding.get("display", "")
            node_attrs["status"] = resource.get("status", "unknown")
            perf = resource.get("performedDateTime") or resource.get("performedPeriod", {}).get("start")
            node_attrs["performedDateTime"] = perf

        G.add_node(node_id, **node_attrs)

        subject = resource.get("subject", {}).get("reference")
        if subject:
            G.add_edge(node_id, subject, relation="subject")
            G.add_edge(subject, node_id, relation="has_resource")

        for reason_ref in resource.get("reasonReference", []):
            ref = reason_ref.get("reference")
            if ref:
                G.add_edge(node_id, ref, relation="indication")
                G.add_edge(ref, node_id, relation="indicated_treatment")

        encounter_ref = resource.get("encounter", {}).get("reference")
        if encounter_ref:
            G.add_edge(node_id, encounter_ref, relation="during_encounter")
            G.add_edge(encounter_ref, node_id, relation="has_observation")

        for result_ref in resource.get("result", []):
            ref = result_ref.get("reference")
            if ref:
                G.add_edge(node_id, ref, relation="has_result")
                G.add_edge(ref, node_id, relation="result_of")

        for member_ref in resource.get("hasMember", []):
            ref = member_ref.get("reference")
            if ref:
                G.add_edge(node_id, ref, relation="has_member")

        for derived_ref in resource.get("derivedFrom", []):
            ref = derived_ref.get("reference")
            if ref:
                G.add_edge(node_id, ref, relation="derived_from")
                G.add_edge(ref, node_id, relation="source_for")

        for based_ref in resource.get("basedOn", []):
            ref = based_ref.get("reference")
            if ref:
                G.add_edge(node_id, ref, relation="based_on")

    return G


class GraphBackedBackend:
    """Benchmark backend using NetworkX graph traversal for FHIR queries."""

    name: str = "graph"

    def answer(
        self,
        question: str,
        bundle: dict[str, Any],
        reference_date: date,
        structured_intent: dict[str, Any] | None = None,
    ) -> QAAnswer:
        if nx is None:
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True,
                           error="networkx not installed")

        G = build_fhir_graph(bundle)

        if structured_intent:
            return self._execute_intent(G, structured_intent, bundle, reference_date)

        resolved = resolve_concept(question)
        if resolved:
            return self._execute_resolved(G, resolved, bundle, reference_date)

        return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True,
                       error="Could not resolve clinical concept from question")

    def _execute_intent(
        self, G: "nx.DiGraph", intent: dict, bundle: dict, reference_date: date,
    ) -> QAAnswer:
        func = intent.get("function", "")
        params = intent.get("params", {})
        code_str = params.get("code", "")

        if func == "cross_resource_temporal":
            return self._graph_cross_resource(
                G, params.get("anchor_code", ""), params.get("target_code", ""),
                params.get("window", "P14D"),
            )

        if func in ("latest_value", "observation_value"):
            return self._graph_latest_observation(G, code_str)

        if func in ("has_condition", "condition_check"):
            return self._graph_has_resource(G, code_str, "Condition")

        if func in ("has_medication", "medication_check"):
            return self._graph_has_medication(G, code_str)

        if func in ("has_allergy", "allergy_check"):
            return self._graph_has_resource(G, code_str, "AllergyIntolerance")

        if func in ("has_procedure", "procedure_check"):
            return self._graph_has_resource(G, code_str, "Procedure")

        if func in ("has_family_history", "family_history_check"):
            return self._graph_has_resource(G, code_str, "FamilyMemberHistory")

        if func in ("patient_age", "age"):
            return self._graph_patient_age(G, reference_date)

        if func in ("observation_count", "observations_in_window", "consecutive_above",
                     "rate_of_change", "trend_declining"):
            from acp_writer.benchmark.backends.current import CurrentImplementationBackend
            backend = CurrentImplementationBackend()
            return backend._run_temporal(func, params, bundle, reference_date, code_str)

        if func == "medications_for_condition":
            return self._graph_medications_for_condition(G, code_str)

        if func == "observations_in_encounter":
            encounter_ref = params.get("encounter_ref", "latest")
            return self._graph_encounter_observations(G, encounter_ref)

        if func == "panel_results":
            return self._graph_panel_results(G, code_str)

        if func == "condition_medications":
            return self._graph_medications_for_condition(G, code_str)

        return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True,
                       error=f"Unsupported function: {func}")

    def _execute_resolved(
        self, G: "nx.DiGraph", resolved: Any, bundle: dict, reference_date: date,
    ) -> QAAnswer:
        if resolved.action == "extract_observation":
            code_token = f"{resolved.system}|{resolved.code}"
            return self._graph_latest_observation(G, code_token)

        if resolved.action == "extract_condition":
            codes = resolved.codes or [f"{resolved.system}|{resolved.code}"]
            for code_token in codes:
                result = self._graph_has_resource(G, code_token, "Condition")
                if result.value is True:
                    return result
            return QAAnswer(value=False, kind="boolean")

        if resolved.action == "extract_medication":
            code_token = f"{resolved.system}|{resolved.code}"
            return self._graph_has_medication(G, code_token)

        if resolved.action == "extract_allergy":
            code_token = f"{resolved.system}|{resolved.code}"
            return self._graph_has_resource(G, code_token, "AllergyIntolerance")

        if resolved.action == "extract_drug_class":
            for code_token in (resolved.codes or []):
                result = self._graph_has_medication(G, code_token)
                if result.value is True:
                    return result
            return QAAnswer(value=False, kind="boolean")

        if resolved.action == "compute_age":
            return self._graph_patient_age(G, reference_date)

        if resolved.action == "compute_bmi":
            weight = self._graph_latest_observation(G, "http://loinc.org|29463-7")
            height = self._graph_latest_observation(G, "http://loinc.org|8302-2")
            if weight.value is not None and height.value is not None:
                try:
                    h_m = float(height.value) / 100
                    bmi = round(float(weight.value) / (h_m ** 2), 1)
                    return QAAnswer(value=bmi, kind="number",
                                  provenance=weight.provenance + height.provenance)
                except (ValueError, ZeroDivisionError):
                    pass
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True,
                       error=f"Unknown action: {resolved.action}")

    def _graph_latest_observation(self, G: "nx.DiGraph", code_token: str) -> QAAnswer:
        """Find the most recent observation matching a code via graph traversal."""
        candidates = []

        for node_id, attrs in G.nodes(data=True):
            if attrs.get("resourceType") != "Observation":
                continue

            components = attrs.get("components", {})
            if code_token in components:
                comp = components[code_token]
                candidates.append((attrs.get("effective_dt"), comp["value"], comp.get("unit"), node_id))
                continue

            if code_token in attrs.get("codes", []):
                if "value" in attrs:
                    candidates.append((attrs.get("effective_dt"), attrs["value"], attrs.get("unit"), node_id))

        if not candidates:
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        candidates.sort(key=lambda c: c[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        _, value, unit, node_id = candidates[0]
        return QAAnswer(value=value, kind="number", provenance=[node_id])

    def _graph_has_resource(self, G: "nx.DiGraph", code_token: str, resource_type: str) -> QAAnswer:
        """Check if a resource with the given code exists via graph traversal."""
        has_any_of_type = False
        for node_id, attrs in G.nodes(data=True):
            if attrs.get("resourceType") != resource_type:
                continue
            has_any_of_type = True
            if code_token in attrs.get("codes", []):
                status = attrs.get("clinicalStatus", "active")
                if status not in ("resolved", "inactive", "remission"):
                    return QAAnswer(value=True, kind="boolean", provenance=[node_id])

        if not has_any_of_type and resource_type in ("Procedure", "FamilyMemberHistory", "DiagnosticReport"):
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        return QAAnswer(value=False, kind="boolean")

    def _graph_has_medication(self, G: "nx.DiGraph", code_token: str) -> QAAnswer:
        for node_id, attrs in G.nodes(data=True):
            if attrs.get("resourceType") not in ("MedicationStatement", "MedicationRequest"):
                continue
            if attrs.get("status") in ("cancelled", "entered-in-error", "stopped"):
                continue
            if code_token in attrs.get("codes", []):
                return QAAnswer(value=True, kind="boolean", provenance=[node_id])
        return QAAnswer(value=False, kind="boolean")

    def _graph_patient_age(self, G: "nx.DiGraph", reference_date: date) -> QAAnswer:
        for node_id, attrs in G.nodes(data=True):
            if attrs.get("resourceType") != "Patient":
                continue
            bd = attrs.get("birthDate")
            if not bd:
                continue
            try:
                birth = date.fromisoformat(bd)
                age = reference_date.year - birth.year
                if (reference_date.month, reference_date.day) < (birth.month, birth.day):
                    age -= 1
                return QAAnswer(value=age, kind="number", provenance=[node_id])
            except ValueError:
                continue
        return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

    def _graph_cross_resource(
        self, G: "nx.DiGraph", anchor_code: str, target_code: str, window: str,
    ) -> QAAnswer:
        from acp_writer.tools.temporal_queries import _parse_duration

        anchor_node = None
        anchor_start = None
        for node_id, attrs in G.nodes(data=True):
            if attrs.get("resourceType") not in ("MedicationStatement", "MedicationRequest"):
                continue
            if anchor_code in attrs.get("codes", []):
                anchor_node = node_id
                anchor_start = attrs.get("start_dt")
                break

        if not anchor_node or not anchor_start:
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        window_td = _parse_duration(window)
        window_end = anchor_start + window_td

        for node_id, attrs in G.nodes(data=True):
            if attrs.get("resourceType") != "Observation":
                continue
            if target_code not in attrs.get("codes", []):
                continue
            eff = attrs.get("effective_dt")
            if eff and anchor_start <= eff <= window_end:
                return QAAnswer(value=True, kind="boolean",
                              provenance=[node_id, anchor_node])

        return QAAnswer(value=False, kind="boolean", provenance=[anchor_node])

    def _graph_medications_for_condition(self, G: "nx.DiGraph", condition_code: str) -> QAAnswer:
        """Find all medications prescribed for a specific condition via graph edges."""
        condition_node = None
        for node_id, attrs in G.nodes(data=True):
            if attrs.get("resourceType") != "Condition":
                continue
            if condition_code in attrs.get("codes", []):
                condition_node = node_id
                break

        if not condition_node:
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        med_names = []
        provenance = [condition_node]
        for pred in G.predecessors(condition_node):
            edge_data = G.edges[pred, condition_node]
            if edge_data.get("relation") != "indication":
                continue
            pred_attrs = G.nodes[pred]
            if pred_attrs.get("resourceType") not in ("MedicationRequest", "MedicationStatement"):
                continue
            if pred_attrs.get("status") in ("cancelled", "entered-in-error", "stopped"):
                continue
            display = pred_attrs.get("display", pred)
            med_names.append(display)
            provenance.append(pred)

        if not med_names:
            return QAAnswer(value=[], kind="code", provenance=provenance)

        return QAAnswer(value=med_names, kind="code", provenance=provenance)

    def _graph_encounter_observations(self, G: "nx.DiGraph", encounter_ref: str) -> QAAnswer:
        """Find all observations from a specific encounter via graph edges."""
        if encounter_ref == "latest":
            enc_nodes = []
            for node_id, attrs in G.nodes(data=True):
                if attrs.get("resourceType") == "Encounter":
                    enc_nodes.append((attrs.get("period_start_dt"), node_id))
            if not enc_nodes:
                return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)
            enc_nodes.sort(key=lambda e: e[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            encounter_ref = enc_nodes[0][1]
        elif not encounter_ref.startswith("Encounter/"):
            encounter_ref = f"Encounter/{encounter_ref}"

        if encounter_ref not in G:
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        obs_list = []
        provenance = [encounter_ref]
        for succ in G.successors(encounter_ref):
            edge_data = G.edges[encounter_ref, succ]
            if edge_data.get("relation") != "has_observation":
                continue
            succ_attrs = G.nodes[succ]
            if succ_attrs.get("resourceType") == "Observation":
                display = succ_attrs.get("display", succ)
                value = succ_attrs.get("value")
                unit = succ_attrs.get("unit", "")
                components = succ_attrs.get("components", {})
                if components:
                    for comp_code, comp_data in components.items():
                        obs_list.append({
                            "name": comp_data.get("display", comp_code),
                            "value": comp_data["value"],
                            "unit": comp_data.get("unit", ""),
                        })
                elif value is not None:
                    obs_list.append({"name": display, "value": value, "unit": unit or ""})
                provenance.append(succ)

        return QAAnswer(
            value=obs_list if obs_list else None,
            kind="code" if obs_list else "insufficient_data",
            provenance=provenance,
            insufficient_data=not obs_list,
        )

    def _graph_panel_results(self, G: "nx.DiGraph", panel_code: str) -> QAAnswer:
        """Find all component results of a diagnostic report/panel via graph edges."""
        panel_node = None
        for node_id, attrs in G.nodes(data=True):
            if attrs.get("resourceType") != "DiagnosticReport":
                continue
            if panel_code in attrs.get("codes", []):
                panel_node = node_id
                break

        if not panel_node:
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        results = []
        provenance = [panel_node]
        for succ in G.successors(panel_node):
            edge_data = G.edges[panel_node, succ]
            if edge_data.get("relation") != "has_result":
                continue
            succ_attrs = G.nodes[succ]
            if succ_attrs.get("resourceType") == "Observation":
                display = succ_attrs.get("display", succ)
                value = succ_attrs.get("value")
                unit = succ_attrs.get("unit", "")
                if value is not None:
                    results.append({"name": display, "value": value, "unit": unit or ""})
                provenance.append(succ)

        return QAAnswer(
            value=results if results else None,
            kind="code" if results else "insufficient_data",
            provenance=provenance,
            insufficient_data=not results,
        )
