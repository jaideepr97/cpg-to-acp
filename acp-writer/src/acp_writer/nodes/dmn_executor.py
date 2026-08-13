"""DMN Executor — evaluate applicable DMN models with pipeline-resolved IPS extraction.

Executes models in topological order, using the concept-resolution pipeline
for open-vocabulary variable resolution. Records full audit trail with
match_basis and degradation markers.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

import mlflow

from acp_writer.state import CarePlanComposerState
from acp_writer.tools.ips_extractor import (
    extract_allergy,
    extract_condition,
    extract_medication,
    extract_observation,
    extract_observation_concept,
    extract_patient_age,
)

logger = logging.getLogger(__name__)

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"

_CONDITION_SYSTEMS = {SNOMED, "http://hl7.org/fhir/sid/icd-10-cm"}
_MEDICATION_SYSTEMS = {RXNORM}

_INACTIVE_CONDITION_STATUSES = {"resolved", "inactive", "remission"}
_INACTIVE_MEDICATION_STATUSES = {"cancelled", "entered-in-error", "stopped"}
_INACTIVE_ALLERGY_STATUSES = {"resolved", "inactive"}


def _filter_active_entries(entries: list, inactive_statuses: set) -> list:
    """Filter inventory entries to those with active (or absent) status."""
    return [e for e in entries if (e.status or "active") not in inactive_statuses]


def _infer_resource_kind(var_name: str, var_type: str) -> str:
    """Infer FHIR resource kind from DMN variable name and type.

    Also consults the concept resolver — if it resolves the term to a
    medication/drug-class action, that takes precedence over name heuristics.
    """
    from acp_writer.tools.concept_resolver import resolve as resolve_concept
    resolved = resolve_concept(var_name)
    if resolved and resolved.action in ("extract_medication", "extract_drug_class"):
        return "medication"
    if resolved and resolved.action == "extract_allergy":
        return "allergy"
    if resolved and resolved.action == "extract_observation":
        return "observation"

    key = var_name.lower()
    if var_type.lower() == "boolean":
        if any(kw in key for kw in ("medication", "drug", "med ", "on ")):
            return "medication"
        if any(kw in key for kw in ("allergy", "allergic")):
            return "allergy"
        return "condition"
    return "observation"


def _try_extract_by_code(
    ips_bundle: dict,
    system: str,
    code: str,
    var_type: str,
) -> tuple[Any, str | None]:
    """Try extracting a value from the IPS using a system|code pair."""
    is_boolean = var_type.lower() == "boolean" if var_type else False

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


@mlflow.trace(name="dmn_extract_via_pipeline")
def _extract_via_pipeline(
    ips_bundle: dict,
    var_name: str,
    var_type: str,
    inventory: Any,
    llm_client: Any,
    reference_date: str | None = None,
) -> tuple[Any, str | None, dict]:
    """Extract a DMN input value using the concept-resolution pipeline.

    Returns (value, fhir_reference, audit_info) where audit_info contains
    match_basis, steps_run, and degraded marker.
    """
    from acp_writer.tools.concept_resolution import resolve_concept_in_bundle

    resource_kind = _infer_resource_kind(var_name, var_type)
    audit = {"match_basis": None, "steps_run": [], "degraded": False}

    try:
        resolution = resolve_concept_in_bundle(
            var_name, inventory, resource_kind, llm_client=llm_client,
        )
    except Exception as exc:
        logger.warning("Pipeline resolution failed for '%s': %s", var_name, exc)
        audit["degraded"] = True
        audit["error"] = str(exc)
        return None, None, audit

    audit["match_basis"] = resolution.match_basis
    audit["steps_run"] = resolution.steps_run

    if not resolution.resolved:
        if resolution.definitive_miss and var_type.lower() == "boolean":
            audit["match_basis"] = "definitive_miss"
            return False, None, audit
        if resolution.unresolved:
            audit["degraded"] = True
        return None, None, audit

    entry = resolution.entries[0]

    if resource_kind == "observation":
        code_tokens = [entry.code_token] if entry.system else None
        display_terms = [entry.display] if (entry.display and not code_tokens) else None
        obs_result = extract_observation_concept(
            ips_bundle, code_tokens=code_tokens, display_terms=display_terms,
        )
        if obs_result.found:
            return obs_result.value, obs_result.fhir_reference, audit
        return None, None, audit

    if resource_kind == "condition":
        active = _filter_active_entries(
            resolution.entries, _INACTIVE_CONDITION_STATUSES,
        )
        if active:
            return True, active[0].fhir_reference, audit
        audit["note"] = f"matched but inactive: {entry.fhir_reference} ({entry.status})"
        return None, None, audit

    if resource_kind == "medication":
        active = _filter_active_entries(
            resolution.entries, _INACTIVE_MEDICATION_STATUSES,
        )
        if active:
            return True, active[0].fhir_reference, audit
        audit["note"] = f"matched but inactive: {entry.fhir_reference} ({entry.status})"
        return None, None, audit

    if resource_kind == "allergy":
        active = _filter_active_entries(
            resolution.entries, _INACTIVE_ALLERGY_STATUSES,
        )
        if active:
            return True, active[0].fhir_reference, audit
        audit["note"] = f"matched but inactive: {entry.fhir_reference} ({entry.status})"
        return None, None, audit

    return None, None, audit


def _execute_resolved(ips_bundle: dict, resolved: Any, reference_date=None) -> tuple[Any, str | None]:
    """Execute an extraction based on a ResolvedConcept (concept-map cache path)."""
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


@mlflow.trace(name="dmn_extract_input_value")
def _extract_input_value(
    ips_bundle: dict,
    var_name: str,
    var_type: str,
    prior_results: dict[str, dict],
    codes: list[str] | None = None,
    reference_date: str | None = None,
    inventory: Any = None,
    llm_client: Any = None,
) -> tuple[Any, str | None, dict]:
    """Extract a DMN input value from the IPS or prior DMN results.

    Layered resolution (priority chain):
    1. Prior DMN results (chained decisions)
    2. DecisionVariable.codes (when provided by cpg-ingester)
    3. Full concept-resolution pipeline (cache → terminology → inventory → LLM)
    4. Audit trail records match_basis and degradation

    Returns (value, fhir_reference, audit_info) tuple.
    """
    key = re.sub(r"([a-z])([A-Z])", r"\1 \2", var_name).lower().strip()
    audit: dict[str, Any] = {}

    for model_output in prior_results.values():
        for decision_name, decision_val in model_output.items():
            if isinstance(decision_val, dict):
                for field_name, field_val in decision_val.items():
                    if field_name.lower() == key:
                        return field_val, None, {"match_basis": "prior_dmn"}
                    composite = f"{decision_name} {field_name}".lower()
                    if composite == key or field_name.lower() in key:
                        return field_val, None, {"match_basis": "prior_dmn"}
            elif decision_name.lower() == key:
                return decision_val, None, {"match_basis": "prior_dmn"}

    if codes:
        for code_token in codes:
            if "|" in code_token:
                system, code = code_token.rsplit("|", 1)
                value, ref = _try_extract_by_code(ips_bundle, system, code, var_type)
                if value is not None:
                    return value, ref, {"match_basis": "decision_variable_codes"}

    if inventory is not None:
        value, ref, audit = _extract_via_pipeline(
            ips_bundle, var_name, var_type, inventory, llm_client, reference_date,
        )
        if value is not None:
            return value, ref, audit
        if audit.get("match_basis") == "definitive_miss":
            return False, None, audit

    logger.warning("Could not extract value for DMN input: %s (type: %s)", var_name, var_type)
    return None, None, {"match_basis": None, "degraded": audit.get("degraded", False)}


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

    from acp_writer.tools.bundle_inventory import build_bundle_inventory
    inventory = build_bundle_inventory(ips_bundle)

    llm_client = None
    try:
        from cpg_contracts import get_llm
        llm_client = get_llm(state)
    except Exception as exc:
        logger.warning("LLM client unavailable for DMN extraction — degraded mode: %s", exc)

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
        input_audit: dict[str, dict] = {}

        today = datetime.now(timezone.utc).date().isoformat()
        expected_inputs = model_info.get("inputs", [])
        for var in expected_inputs:
            value, ref, var_audit = _extract_input_value(
                ips_bundle, var["name"], var.get("type", "string"), prior_results,
                codes=var.get("codes"),
                reference_date=today,
                inventory=inventory,
                llm_client=llm_client,
            )
            if value is not None:
                inputs[var["name"]] = value
            if ref:
                fhir_refs.append(ref)
            input_audit[var["name"]] = var_audit

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
                "input_resolution": input_audit,
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
                "input_resolution": input_audit,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            })

    return {"dmn_results": audit_trail}
