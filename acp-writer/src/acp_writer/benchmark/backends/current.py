"""CurrentImplementationBackend — wraps the acp-writer extraction layer.

Uses the full extraction capability: direct extraction functions,
temporal index + primitives, and variable name resolution.
"""

import re
from datetime import date
from typing import Any

from acp_writer.benchmark.models import QAAnswer
from acp_writer.nodes.dmn_executor import KNOWN_VARIABLE_MAP
from acp_writer.tools.bundle_inventory import build_bundle_inventory
from acp_writer.tools.concept_resolution import resolve_concept_in_bundle
from acp_writer.tools.ips_extractor import (
    extract_allergy,
    extract_condition,
    extract_condition_concept,
    extract_diagnostic_report,
    extract_family_history,
    extract_medication,
    extract_medication_concept,
    extract_observation,
    extract_observation_concept,
    extract_patient_age,
    extract_procedure,
)
from acp_writer.tools.temporal_index import build_temporal_index
from acp_writer.tools.concept_resolver import resolve as resolve_concept
from acp_writer.tools.temporal_queries import (
    consecutive_above,
    cross_resource_temporal,
    observation_count,
    observations_in_window,
    rate_of_change,
)

_OBSERVATION_FUNCTIONS = {"latest_value", "observation_value"}
_CONDITION_FUNCTIONS = {"has_condition", "condition_check"}
_MEDICATION_FUNCTIONS = {"has_medication", "medication_check"}
_ALLERGY_FUNCTIONS = {"has_allergy", "allergy_check"}
_PROCEDURE_FUNCTIONS = {"has_procedure", "procedure_check"}
_FAMILY_HISTORY_FUNCTIONS = {"has_family_history", "family_history_check"}
_DIAGNOSTIC_REPORT_FUNCTIONS = {"has_diagnostic_report", "diagnostic_report_check"}
_AGE_FUNCTIONS = {"patient_age", "age"}
_TEMPORAL_FUNCTIONS = {
    "observation_count", "observations_in_window",
    "consecutive_above", "rate_of_change",
    "cross_resource_temporal", "trend_declining",
    "observation_at",
}
_GRAPH_ONLY_FUNCTIONS = {
    "medications_for_condition", "observations_in_encounter",
    "panel_results", "condition_medications",
}


class CurrentImplementationBackend:
    name: str = "current"

    def answer(
        self,
        question: str,
        bundle: dict[str, Any],
        reference_date: date,
        structured_intent: dict[str, Any] | None = None,
    ) -> QAAnswer:
        if structured_intent is None:
            return self._try_variable_map(question, bundle, reference_date)

        func = structured_intent.get("function", "")
        params = structured_intent.get("params", {})
        code_str = params.get("code", "")

        if func in _TEMPORAL_FUNCTIONS and func == "cross_resource_temporal":
            return self._run_temporal(func, params, bundle, reference_date, "")

        if "|" not in code_str:
            return QAAnswer(
                value=None,
                kind="insufficient_data",
                insufficient_data=True,
                error="Cannot parse code from structured_intent",
            )

        system, code = code_str.rsplit("|", 1)

        if func in _OBSERVATION_FUNCTIONS:
            return self._extract_observation(bundle, system, code)

        if func in _CONDITION_FUNCTIONS:
            return self._extract_condition(bundle, system, code)

        if func in _MEDICATION_FUNCTIONS:
            return self._extract_medication(bundle, system, code)

        if func in _ALLERGY_FUNCTIONS:
            return self._extract_allergy(bundle, system, code)

        if func in _PROCEDURE_FUNCTIONS:
            result = extract_procedure(bundle, system, code)
            return QAAnswer(
                value=result.found if result.found else False,
                kind="boolean",
                provenance=[result.fhir_reference] if result.fhir_reference else [],
                insufficient_data=not result.found,
            )

        if func in _FAMILY_HISTORY_FUNCTIONS:
            result = extract_family_history(bundle, system, code)
            return QAAnswer(
                value=result.found if result.found else False,
                kind="boolean",
                provenance=[result.fhir_reference] if result.fhir_reference else [],
                insufficient_data=not result.found,
            )

        if func in _DIAGNOSTIC_REPORT_FUNCTIONS:
            result = extract_diagnostic_report(bundle, system, code)
            return QAAnswer(
                value=result.found if result.found else False,
                kind="boolean",
                provenance=[result.fhir_reference] if result.fhir_reference else [],
                insufficient_data=not result.found,
            )

        if func in _AGE_FUNCTIONS:
            result = extract_patient_age(bundle, reference_date)
            if result.found:
                return QAAnswer(
                    value=result.value, kind="number",
                    provenance=[result.fhir_reference] if result.fhir_reference else [],
                )
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        if func in _TEMPORAL_FUNCTIONS:
            return self._run_temporal(func, params, bundle, reference_date, code_str)

        if func in _GRAPH_ONLY_FUNCTIONS:
            return QAAnswer(
                value=None, kind="insufficient_data", insufficient_data=True,
                error=f"Reference traversal not supported in flat extraction: {func}",
            )

        return QAAnswer(
            value=None,
            kind="insufficient_data",
            insufficient_data=True,
            error=f"Current implementation does not support function: {func}",
        )

    def _extract_observation(
        self, bundle: dict, system: str, code: str
    ) -> QAAnswer:
        result = extract_observation(bundle, system, code)
        if result.found:
            return QAAnswer(
                value=result.value,
                kind="number",
                provenance=[result.fhir_reference] if result.fhir_reference else [],
            )
        return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

    def _extract_condition(
        self, bundle: dict, system: str, code: str
    ) -> QAAnswer:
        result = extract_condition(bundle, system, code)
        return QAAnswer(
            value=result.found,
            kind="boolean",
            provenance=[result.fhir_reference] if result.fhir_reference else [],
        )

    def _extract_medication(
        self, bundle: dict, system: str, code: str
    ) -> QAAnswer:
        result = extract_medication(bundle, system, code)
        return QAAnswer(
            value=result.found,
            kind="boolean",
            provenance=[result.fhir_reference] if result.fhir_reference else [],
        )

    def _extract_allergy(
        self, bundle: dict, system: str, code: str
    ) -> QAAnswer:
        result = extract_allergy(bundle, system, code)
        return QAAnswer(
            value=result.found,
            kind="boolean",
            provenance=[result.fhir_reference] if result.fhir_reference else [],
        )

    def _run_temporal(
        self, func: str, params: dict, bundle: dict, reference_date: date, code_str: str,
    ) -> QAAnswer:
        """Route temporal functions to the temporal query primitives."""
        index = build_temporal_index(bundle)

        if func == "observations_in_window":
            result = observations_in_window(
                index, code_str, params.get("duration", "P12M"), reference_date,
            )
            if result.found and isinstance(result.value, list):
                latest = result.value[0] if result.value else None
                return QAAnswer(
                    value=latest["value"] if latest else None,
                    kind="number",
                    provenance=result.provenance,
                )
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        if func == "observation_count":
            result = observation_count(
                index, code_str,
                params.get("duration", "P12M"),
                reference_date,
                threshold=params.get("threshold"),
                comparator=params.get("comparator"),
            )
            if result.found:
                return QAAnswer(
                    value=result.value, kind="count", provenance=result.provenance,
                )
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        if func == "consecutive_above":
            result = consecutive_above(
                index, code_str, params.get("threshold", 0), reference_date,
            )
            if result.found:
                return QAAnswer(
                    value=result.value, kind="count", provenance=result.provenance,
                )
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        if func == "rate_of_change":
            result = rate_of_change(
                index, code_str, params.get("duration", "P1Y"), reference_date,
            )
            if result.found:
                return QAAnswer(
                    value=result.value, kind="number", provenance=result.provenance,
                )
            return QAAnswer(
                value=None, kind="insufficient_data", insufficient_data=True,
                error=result.data_quality,
            )

        if func == "cross_resource_temporal":
            anchor_code = params.get("anchor_code", "")
            target_code = params.get("target_code", "")
            window = params.get("window", "P14D")
            result = cross_resource_temporal(
                index, bundle, anchor_code, target_code, window,
            )
            if result.found:
                return QAAnswer(
                    value=result.value, kind="boolean", provenance=result.provenance,
                )
            return QAAnswer(
                value=None, kind="insufficient_data", insufficient_data=True,
                error=result.data_quality,
            )

        if func == "trend_declining":
            obs_list = index.get_observations(code_str)
            dated = [o for o in obs_list if o.has_date and o.effective_dt is not None]
            if len(dated) < 2:
                return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)
            dated.sort(key=lambda o: o.effective_dt, reverse=True)
            try:
                declining = float(dated[0].value) < float(dated[1].value)
            except (ValueError, TypeError):
                return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)
            return QAAnswer(
                value=declining, kind="boolean",
                provenance=[dated[0].fhir_reference, dated[1].fhir_reference],
            )

        if func == "observation_at":
            target_str = params.get("target_date", "")
            from acp_writer.tools.temporal_index import _parse_datetime
            target_dt = _parse_datetime(target_str)
            if not target_dt:
                return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)
            obs_list = index.get_observations(code_str)
            dated = [o for o in obs_list if o.has_date and o.effective_dt is not None]
            if not dated:
                return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)
            closest = min(dated, key=lambda o: abs((o.effective_dt - target_dt).total_seconds()))
            return QAAnswer(
                value=closest.value, kind="number",
                provenance=[closest.fhir_reference],
            )

        return QAAnswer(
            value=None, kind="insufficient_data", insufficient_data=True,
            error=f"Unknown temporal function: {func}",
        )

    def _try_variable_map(
        self, question: str, bundle: dict, reference_date: date,
    ) -> QAAnswer:
        """Resolve a question using the concept resolver, falling back to KNOWN_VARIABLE_MAP."""
        resolved = resolve_concept(question)
        if resolved:
            return self._execute_resolved(resolved, bundle, reference_date)

        key = re.sub(r"([a-z])([A-Z])", r"\1 \2", question).lower().strip()
        for map_key, (system, code, extract_type) in KNOWN_VARIABLE_MAP.items():
            if map_key in key:
                if extract_type == "observation":
                    return self._extract_observation(bundle, system, code)
                elif extract_type == "condition":
                    return self._extract_condition(bundle, system, code)
                elif extract_type == "medication":
                    return self._extract_medication(bundle, system, code)

        return QAAnswer(
            value=None,
            kind="insufficient_data",
            insufficient_data=True,
            error="Could not resolve clinical concept from question",
        )

    def _execute_resolved(
        self, resolved: Any, bundle: dict, reference_date: date,
    ) -> QAAnswer:
        """Execute an extraction based on a ResolvedConcept."""
        if resolved.action == "extract_observation":
            code_tokens = [f"{resolved.system}|{resolved.code}"] if resolved.system and resolved.code else []
            display_terms = [resolved.code] if resolved.code else []
            result = extract_observation_concept(bundle, code_tokens=code_tokens or None, display_terms=display_terms or None)
            if result.found:
                return QAAnswer(
                    value=result.value, kind="number",
                    provenance=[result.fhir_reference] if result.fhir_reference else [],
                )
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        if resolved.action == "extract_condition":
            code_tokens = resolved.codes or ([f"{resolved.system}|{resolved.code}"] if resolved.system else [])
            result = extract_condition_concept(bundle, code_tokens=code_tokens or None, display_terms=None)
            return QAAnswer(
                value=result.found,
                kind="boolean",
                provenance=[result.fhir_reference] if result.fhir_reference else [],
            )

        if resolved.action == "extract_medication":
            code_tokens = [f"{resolved.system}|{resolved.code}"] if resolved.system and resolved.code else []
            display_terms = [resolved.code.split("|")[-1]] if resolved.code else []
            result = extract_medication_concept(bundle, code_tokens=code_tokens or None, display_terms=display_terms or None)
            return QAAnswer(
                value=result.found,
                kind="boolean",
                provenance=[result.fhir_reference] if result.fhir_reference else [],
            )

        if resolved.action == "extract_allergy":
            return self._extract_allergy(bundle, resolved.system, resolved.code)

        if resolved.action == "extract_drug_class":
            code_tokens = resolved.codes or []
            result = extract_medication_concept(bundle, code_tokens=code_tokens or None, display_terms=None)
            if result.found:
                return QAAnswer(
                    value=True, kind="boolean",
                    provenance=[result.fhir_reference] if result.fhir_reference else [],
                )
            return QAAnswer(value=False, kind="boolean")

        if resolved.action == "compute_age":
            result = extract_patient_age(bundle, reference_date)
            if result.found:
                return QAAnswer(
                    value=result.value, kind="number",
                    provenance=[result.fhir_reference] if result.fhir_reference else [],
                )
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        if resolved.action == "compute_bmi":
            weight_result = extract_observation(bundle, "http://loinc.org", "29463-7")
            height_result = extract_observation(bundle, "http://loinc.org", "8302-2")
            if weight_result.found and height_result.found:
                try:
                    weight_kg = float(weight_result.value)
                    height_cm = float(height_result.value)
                    height_m = height_cm / 100
                    bmi = round(weight_kg / (height_m ** 2), 1)
                    provenance = []
                    if weight_result.fhir_reference:
                        provenance.append(weight_result.fhir_reference)
                    if height_result.fhir_reference:
                        provenance.append(height_result.fhir_reference)
                    return QAAnswer(value=bmi, kind="number", provenance=provenance)
                except (ValueError, TypeError, ZeroDivisionError):
                    pass
            return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

        return QAAnswer(
            value=None, kind="insufficient_data", insufficient_data=True,
            error=f"Unknown action: {resolved.action}",
        )
