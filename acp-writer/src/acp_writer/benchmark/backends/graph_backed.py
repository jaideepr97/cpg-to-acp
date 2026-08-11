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

        G.add_node(node_id, **node_attrs)

        subject = resource.get("subject", {}).get("reference")
        if subject:
            G.add_edge(node_id, subject, relation="subject")
            G.add_edge(subject, node_id, relation="has_resource")

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
