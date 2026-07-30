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
from acp_writer.tools.ips_extractor import (
    extract_condition,
    extract_medication,
    extract_observation,
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


def _extract_input_value(
    ips_bundle: dict,
    var_name: str,
    var_type: str,
    prior_results: dict[str, dict],
) -> tuple[Any, str | None]:
    """Extract a DMN input value from the IPS or prior DMN results.

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

        expected_inputs = model_info.get("inputs", [])
        for var in expected_inputs:
            value, ref = _extract_input_value(
                ips_bundle, var["name"], var.get("type", "string"), prior_results
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
