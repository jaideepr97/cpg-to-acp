"""DMN Executor — evaluate applicable DMN models with targeted IPS extraction.

Executes models in topological order, using IPS Extractor tool
for on-demand data extraction. Records full audit trail.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

import mlflow

from acp_writer.state import CarePlanComposerState
from acp_writer.tools.concept_resolver import resolve as resolve_concept
from acp_writer.tools.ips_extractor import (
    extract_allergy,
    extract_condition,
    extract_medication,
    extract_observation,
    extract_patient_age,
    extract_procedure,
)

logger = logging.getLogger(__name__)

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"

KNOWN_VARIABLE_MAP: dict[str, tuple[str, str, str]] = {
    "systolic bp": (LOINC, "8480-6", "observation"),
    "diastolic bp": (LOINC, "8462-4", "observation"),
    "has diabetes": (SNOMED, "44054006", "condition"),
    "has kidney disease": (SNOMED, "709044004", "condition"),
    "has chronic kidney disease": (SNOMED, "709044004", "condition"),
    "has ckd": (SNOMED, "709044004", "condition"),
}

_CONDITION_SYSTEMS = {SNOMED, "http://hl7.org/fhir/sid/icd-10-cm"}
_MEDICATION_SYSTEMS = {RXNORM}


def _try_extract_by_code(
    ips_bundle: dict,
    system: str,
    code: str,
    var_type: str,
) -> tuple[Any, str | None]:
    """Try extracting a value from the IPS using a system|code pair.

    Infers the resource type from the terminology system and variable type.
    """
    key_lower = var_type.lower() if var_type else ""
    is_boolean = key_lower == "boolean"

    if is_boolean and system in _CONDITION_SYSTEMS:
        result = extract_condition(ips_bundle, system, code)
        return result.found, result.fhir_reference

    if is_boolean and system in _MEDICATION_SYSTEMS:
        result = extract_medication(ips_bundle, system, code)
        return result.found, result.fhir_reference

    result = extract_observation(ips_bundle, system, code)
    if result.found:
        return result.value, result.fhir_reference

    if not is_boolean:
        result = extract_condition(ips_bundle, system, code)
        if result.found:
            return result.found, result.fhir_reference

    return None, None


def _execute_resolved(ips_bundle: dict, resolved: Any, reference_date=None) -> tuple[Any, str | None]:
    """Execute an extraction based on a ResolvedConcept."""
    if resolved.action == "extract_observation":
        result = extract_observation(ips_bundle, resolved.system, resolved.code)
        if result.found:
            return result.value, result.fhir_reference
        return None, None

    if resolved.action == "extract_condition":
        all_codes = resolved.codes or [f"{resolved.system}|{resolved.code}"]
        for code_token in all_codes:
            if "|" not in code_token:
                continue
            sys, cd = code_token.rsplit("|", 1)
            result = extract_condition(ips_bundle, sys, cd)
            if result.found:
                return True, result.fhir_reference
        return False, None

    if resolved.action == "extract_medication":
        result = extract_medication(ips_bundle, resolved.system, resolved.code)
        return result.found, result.fhir_reference

    if resolved.action == "extract_allergy":
        result = extract_allergy(ips_bundle, resolved.system, resolved.code)
        return result.found, result.fhir_reference

    if resolved.action == "extract_drug_class":
        for code_token in (resolved.codes or []):
            if "|" not in code_token:
                continue
            sys, cd = code_token.rsplit("|", 1)
            result = extract_medication(ips_bundle, sys, cd)
            if result.found:
                return True, result.fhir_reference
        return False, None

    if resolved.action == "compute_age" and reference_date:
        from datetime import date
        if isinstance(reference_date, str):
            reference_date = date.fromisoformat(reference_date)
        result = extract_patient_age(ips_bundle, reference_date)
        if result.found:
            return result.value, result.fhir_reference
        return None, None

    if resolved.action == "compute_bmi":
        w = extract_observation(ips_bundle, LOINC, "29463-7")
        h = extract_observation(ips_bundle, LOINC, "8302-2")
        if w.found and h.found:
            try:
                bmi = round(float(w.value) / (float(h.value) / 100) ** 2, 1)
                return bmi, w.fhir_reference
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        return None, None

    return None, None


def _extract_input_value(
    ips_bundle: dict,
    var_name: str,
    var_type: str,
    prior_results: dict[str, dict],
    codes: list[str] | None = None,
    reference_date: str | None = None,
) -> tuple[Any, str | None]:
    """Extract a DMN input value from the IPS or prior DMN results.

    Layered resolution (priority chain):
    1. Prior DMN results (chained decisions)
    2. DecisionVariable.codes (when provided by cpg-ingester)
    3. Concept resolver (deterministic clinical term → FHIR code mapping)
    4. KNOWN_VARIABLE_MAP (legacy hardcoded fallback)

    Returns (value, fhir_reference) tuple.
    """
    key = re.sub(r"([a-z])([A-Z])", r"\1 \2", var_name).lower().strip()

    for model_output in prior_results.values():
        for decision_name, decision_val in model_output.items():
            if isinstance(decision_val, dict):
                for field_name, field_val in decision_val.items():
                    if field_name.lower() == key:
                        return field_val, None
                    composite = f"{decision_name} {field_name}".lower()
                    if composite == key or field_name.lower() in key:
                        return field_val, None
            elif decision_name.lower() == key:
                return decision_val, None

    if codes:
        for code_token in codes:
            if "|" in code_token:
                system, code = code_token.rsplit("|", 1)
                value, ref = _try_extract_by_code(ips_bundle, system, code, var_type)
                if value is not None:
                    return value, ref

    resolved = resolve_concept(var_name)
    if resolved:
        value, ref = _execute_resolved(ips_bundle, resolved, reference_date)
        if value is not None:
            return value, ref

    mapping = KNOWN_VARIABLE_MAP.get(key)
    if mapping:
        system, code, extract_type = mapping
        if extract_type == "observation":
            result = extract_observation(ips_bundle, system, code)
            if result.found:
                return result.value, result.fhir_reference
        elif extract_type == "condition":
            result = extract_condition(ips_bundle, system, code)
            return result.found, result.fhir_reference
        elif extract_type == "medication":
            result = extract_medication(ips_bundle, system, code)
            return result.found, result.fhir_reference

    logger.warning("Could not extract value for DMN input: %s (type: %s)", var_name, var_type)
    return None, None


@mlflow.trace(name="dmn_executor")
def dmn_executor(state: CarePlanComposerState) -> dict:
    """Execute applicable DMN models in topological order."""
    logger.info("── DMN Executor ──")
    from acp_writer.api import _dynamic_models, _evaluate_jit

    ips_bundle = state.get("ips_bundle", {})
    applicable_models = state.get("applicable_dmn_models", [])
    dependency_graph = state.get("dmn_dependency_graph", [])

    if not applicable_models:
        logger.info("No applicable DMN models — skipping execution")
        return {"dmn_results": []}

    model_map = {m["id"]: m for m in applicable_models}
    prior_results: dict[str, dict] = {}
    audit_trail: list[dict[str, Any]] = []

    execution_order: list[str] = []
    if dependency_graph:
        for level in dependency_graph:
            execution_order.extend(level)
    else:
        execution_order = [m["id"] for m in applicable_models]

    for model_id in execution_order:
        model_info = model_map.get(model_id)
        if not model_info:
            continue

        deployed = _dynamic_models.get(model_id)
        if not deployed:
            logger.warning("Model %s not deployed — skipping", model_id)
            audit_trail.append({
                "model_id": model_id,
                "model_name": model_info.get("name", model_id),
                "inputs": {},
                "outputs": {},
                "fhir_references": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": "Model not deployed",
            })
            continue

        inputs: dict[str, Any] = {}
        fhir_refs: list[str] = []

        today = datetime.now(timezone.utc).date().isoformat()
        expected_inputs = model_info.get("inputs", [])
        for var in expected_inputs:
            value, ref = _extract_input_value(
                ips_bundle, var["name"], var.get("type", "string"), prior_results,
                codes=var.get("codes"),
                reference_date=today,
            )
            if value is not None:
                inputs[var["name"]] = value
            if ref:
                fhir_refs.append(ref)

        missing = [v["name"] for v in expected_inputs if v["name"] not in inputs]
        if missing:
            logger.warning("DMN model %s missing inputs: %s", model_info.get("name"), missing)

        logger.info("Evaluating DMN model: %s with inputs: %s", model_info.get("name"), inputs)

        try:
            result = _evaluate_jit(deployed["dmn_xml"], inputs)
            prior_results[model_id] = result

            audit_trail.append({
                "model_id": model_id,
                "model_name": model_info.get("name", model_id),
                "inputs": inputs,
                "outputs": result,
                "fhir_references": fhir_refs,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            logger.info("DMN result for %s: %s", model_info.get("name"), result)

        except Exception as e:
            logger.error("DMN evaluation failed for %s: %s", model_id, e)
            audit_trail.append({
                "model_id": model_id,
                "model_name": model_info.get("name", model_id),
                "inputs": inputs,
                "outputs": {},
                "fhir_references": fhir_refs,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            })

    return {"dmn_results": audit_trail}
