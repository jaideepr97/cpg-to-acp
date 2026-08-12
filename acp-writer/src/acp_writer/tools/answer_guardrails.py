"""Deterministic answer verification guardrails.

Code-level checks on the agent's final answer before it becomes
a QAAnswer. Each guardrail is traced and logs when it fires.
"""

import logging
from typing import Any

import mlflow

from acp_writer.tools.bundle_inventory import BundleInventory
from acp_writer.tools.concept_resolution import resolve_concept_in_bundle
from acp_writer.tools.ips_extractor import _get_resources_with_entry, _resource_ref

logger = logging.getLogger(__name__)


@mlflow.trace(name="guardrail_provenance_required")
def check_provenance_required(answer: dict) -> dict:
    """Non-insufficient_data answers require provenance; else downgrade."""
    if answer.get("insufficient_data"):
        return answer

    if answer.get("answer") is not None and not answer.get("provenance"):
        logger.info("Guardrail: downgrading answer without provenance")
        return {
            "answer": None,
            "provenance": [],
            "insufficient_data": True,
            "guardrail": "provenance_required",
            "original_answer": answer.get("answer"),
        }
    return answer


@mlflow.trace(name="guardrail_value_consistency")
def check_value_consistency(answer: dict, bundle: dict) -> dict:
    """Numeric answers must match a value in a cited resource."""
    if answer.get("insufficient_data"):
        return answer

    value = answer.get("answer")
    if not isinstance(value, (int, float)):
        return answer

    provenance = answer.get("provenance", [])
    if not provenance:
        return answer

    for ref in provenance:
        if _value_in_resource(value, ref, bundle):
            return answer

    logger.info("Guardrail: numeric value %s not found in cited resources %s", value, provenance)
    return {
        "answer": None,
        "provenance": provenance,
        "insufficient_data": True,
        "guardrail": "value_consistency",
        "original_answer": value,
    }


def _value_in_resource(value: float, ref: str, bundle: dict) -> bool:
    """Check if a numeric value appears in a resource referenced by ref."""
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        resource_ref = _resource_ref(resource, entry)
        if resource_ref != ref:
            continue

        for val_field in ["valueQuantity", "valueString"]:
            v = resource.get(val_field)
            if isinstance(v, dict) and v.get("value") is not None:
                try:
                    if abs(float(v["value"]) - value) < 0.01:
                        return True
                except (ValueError, TypeError):
                    pass

        for component in resource.get("component", []):
            vq = component.get("valueQuantity")
            if vq and vq.get("value") is not None:
                try:
                    if abs(float(vq["value"]) - value) < 0.01:
                        return True
                except (ValueError, TypeError):
                    pass

    return True  # can't verify → don't block


@mlflow.trace(name="guardrail_concept_consistency")
def check_concept_consistency(
    answer: dict,
    question_term: str,
    inventory: BundleInventory,
) -> dict:
    """Verify cited resource matches the question's concept."""
    if answer.get("insufficient_data"):
        return answer

    provenance = answer.get("provenance", [])
    if not provenance:
        return answer

    resolution = resolve_concept_in_bundle(
        question_term, inventory, resource_kind="observation", llm_client=None,
    )
    if not resolution.resolved:
        return answer

    resolved_refs = {e.fhir_reference for e in resolution.entries}
    cited_refs = set(provenance)

    if cited_refs & resolved_refs:
        return answer

    logger.info(
        "Guardrail: concept consistency mismatch. Question '%s' resolved to %s but answer cites %s",
        question_term, resolved_refs, cited_refs,
    )
    return {
        "answer": None,
        "provenance": provenance,
        "insufficient_data": True,
        "guardrail": "concept_consistency",
        "original_answer": answer.get("answer"),
    }


@mlflow.trace(name="guardrail_conflict_enforcement")
def check_conflict_enforcement(answer: dict, bundle: dict, inventory: BundleInventory) -> dict:
    """Downgrade answers based on conflicting data (same concept, different values)."""
    if answer.get("insufficient_data"):
        return answer

    provenance = answer.get("provenance", [])
    if not provenance:
        return answer

    values_by_code: dict[str, list[float]] = {}
    for entry_item in inventory.entries:
        if entry_item.resource_type != "Observation":
            continue
        if entry_item.fhir_reference not in provenance:
            continue

        for other in inventory.entries:
            if other.resource_type != "Observation":
                continue
            if other.code_token != entry_item.code_token:
                continue
            if other.fhir_reference == entry_item.fhir_reference:
                continue
            if (other.date or "")[:10] == (entry_item.date or "")[:10]:
                vals = values_by_code.setdefault(entry_item.code_token, [])
                # Look up actual values
                for e in bundle.get("entry", []):
                    r = e.get("resource", {})
                    ref = _resource_ref(r, e)
                    if ref in (entry_item.fhir_reference, other.fhir_reference):
                        vq = r.get("valueQuantity", {})
                        if vq.get("value") is not None:
                            vals.append(float(vq["value"]))

    for code_token, vals in values_by_code.items():
        unique = set(vals)
        if len(unique) > 1:
            logger.info("Guardrail: conflicting values for %s: %s", code_token, unique)
            return {
                "answer": None,
                "provenance": provenance,
                "insufficient_data": True,
                "guardrail": "conflict_enforcement",
                "original_answer": answer.get("answer"),
            }

    return answer


def verify_answer(
    answer: dict,
    question: str,
    bundle: dict,
    inventory: BundleInventory,
) -> dict:
    """Run all guardrails on an answer. Returns the verified (possibly downgraded) answer."""
    answer = check_provenance_required(answer)
    answer = check_value_consistency(answer, bundle)
    answer = check_concept_consistency(answer, question, inventory)
    answer = check_conflict_enforcement(answer, bundle, inventory)
    return answer
