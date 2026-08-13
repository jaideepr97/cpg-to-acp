"""Deterministic answer verification guardrails.

One choke point, every path, fail-closed. Verification lives at the
QAAnswer boundary — no answer leaves the backend unverified.
Refusal is decided by code, never by the agent.
"""

import logging
from typing import Any

import mlflow

from acp_writer.benchmark.models import QAAnswer
from acp_writer.tools.bundle_inventory import BundleInventory, InventoryEntry
from acp_writer.tools.ips_extractor import _get_resources_with_entry, _resource_ref, _normalize_display

logger = logging.getLogger(__name__)


@mlflow.trace(name="guardrail_verify_answer")
def verify_answer(
    answer: QAAnswer,
    question: str,
    bundle: dict,
    inventory: BundleInventory,
) -> QAAnswer:
    """Run all guardrails on a QAAnswer. Returns the verified (possibly downgraded) answer.

    Called on EVERY answer path — resolver, query-plan, and agent.
    """
    if answer.insufficient_data:
        return answer

    result = _check_provenance_required(answer)
    if result.insufficient_data:
        return result

    result = _check_value_consistency(result, bundle)
    if result.insufficient_data:
        return result

    result = _check_concept_consistency(result, question, inventory)
    if result.insufficient_data:
        return result

    result = _check_conflict(result, bundle, inventory)
    return result


def _downgrade(answer: QAAnswer, guardrail: str, reason: str) -> QAAnswer:
    """Produce a guardrail-downgraded insufficient_data answer."""
    logger.info("Guardrail [%s]: downgrading answer. Reason: %s. Original: %s",
                guardrail, reason, answer.value)
    return QAAnswer(
        value=None,
        kind="insufficient_data",
        provenance=answer.provenance,
        insufficient_data=True,
        error=f"guardrail:{guardrail}",
        answered_by="guardrail_downgrade",
        resolution_basis=f"{guardrail}: {reason}",
    )


@mlflow.trace(name="guardrail_provenance_required")
def _check_provenance_required(answer: QAAnswer) -> QAAnswer:
    """Non-insufficient_data answers require provenance; else downgrade."""
    if answer.value is not None and not answer.provenance:
        return _downgrade(answer, "provenance_required", "answer without provenance")
    logger.debug("Guardrail [provenance_required]: passed (provenance present)")
    return answer


@mlflow.trace(name="guardrail_value_consistency")
def _check_value_consistency(answer: QAAnswer, bundle: dict) -> QAAnswer:
    """Numeric answers must match a value in a cited resource. Fail closed."""
    if not isinstance(answer.value, (int, float)):
        logger.debug("Guardrail [value_consistency]: skipped (non-numeric answer)")
        return answer

    if not answer.provenance:
        logger.debug("Guardrail [value_consistency]: skipped (no provenance)")
        return answer

    for ref in answer.provenance:
        if _value_in_resource(answer.value, ref, bundle):
            logger.debug("Guardrail [value_consistency]: passed (value found in %s)", ref)
            return answer

    return _downgrade(
        answer, "value_consistency",
        f"numeric value {answer.value} not found in cited resources {answer.provenance}",
    )


def _value_in_resource(value: float, ref: str, bundle: dict) -> bool:
    """Check if a numeric value appears in a resource referenced by ref.

    Returns False (fail closed) if the resource cannot be found.
    """
    resource_found = False

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        resource_ref = _resource_ref(resource, entry)
        if resource_ref != ref:
            continue
        resource_found = True

        for val_field in ["valueQuantity"]:
            v = resource.get(val_field)
            if isinstance(v, dict) and v.get("value") is not None:
                try:
                    if abs(float(v["value"]) - value) < 0.01:
                        return True
                except (ValueError, TypeError):
                    pass

        vs = resource.get("valueString")
        if vs is not None:
            try:
                if abs(float(vs) - value) < 0.01:
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

    if not resource_found:
        logger.debug("Guardrail [value_consistency]: resource %s not found in bundle — fail closed", ref)
        return False

    return False


@mlflow.trace(name="guardrail_concept_consistency")
def _check_concept_consistency(
    answer: QAAnswer,
    question_term: str,
    inventory: BundleInventory,
) -> QAAnswer:
    """Verify cited resource matches the question's concept.

    Uses terminology cross-check (independent of the resolution pipeline)
    to avoid circular validation.
    """
    if not answer.provenance:
        logger.debug("Guardrail [concept_consistency]: skipped (no provenance)")
        return answer

    if not isinstance(answer.value, (int, float)):
        logger.debug("Guardrail [concept_consistency]: skipped (non-numeric answer)")
        return answer

    cited_entries = [
        e for e in inventory.entries
        if e.fhir_reference in answer.provenance and e.resource_type == "Observation"
    ]

    if not cited_entries:
        logger.debug("Guardrail [concept_consistency]: skipped (no cited observations in inventory)")
        return answer

    term_candidates = _get_terminology_candidates(question_term)

    if term_candidates is None:
        logger.debug("Guardrail [concept_consistency]: skipped (terminology unavailable)")
        return answer

    if not term_candidates:
        norm_term = _normalize_display(question_term)
        for entry in cited_entries:
            norm_display = _normalize_display(entry.display) if entry.display else ""
            if norm_term and norm_display and (norm_term in norm_display or norm_display in norm_term):
                logger.debug("Guardrail [concept_consistency]: passed (display match: %s ~ %s)",
                            question_term, entry.display)
                return answer
        logger.debug("Guardrail [concept_consistency]: no terminology candidates and no display match — fail closed")
        return _downgrade(
            answer, "concept_consistency",
            f"cannot verify '{question_term}' matches cited resources (no terminology candidates)",
        )

    cited_tokens = {e.code_token for e in cited_entries if e.system and e.code}

    if cited_tokens & term_candidates:
        logger.debug("Guardrail [concept_consistency]: passed (code match)")
        return answer

    return _downgrade(
        answer, "concept_consistency",
        f"'{question_term}' resolved to codes {term_candidates} but cited resources have {cited_tokens}",
    )


def _get_terminology_candidates(term: str) -> set[str] | None:
    """Get candidate code tokens for a term via terminology lookup.

    Returns a set of system|code tokens, empty set if no candidates found,
    or None if terminology services are unavailable.
    """
    try:
        from acp_writer.tools.terminology_lookup import find_candidates
        from acp_writer.tools.concept_resolution import (
            LOINC_SYSTEM, SNOMED_SYSTEM, RXNORM_SYSTEM, ICD10_SYSTEM,
        )
    except ImportError:
        return None

    candidates = set()
    for system in [LOINC_SYSTEM, SNOMED_SYSTEM, RXNORM_SYSTEM, ICD10_SYSTEM]:
        try:
            results = find_candidates(system, term, n=5)
            for r in results:
                if r.found and r.code:
                    candidates.add(f"{r.system}|{r.code}")
        except Exception:
            continue

    from acp_writer.tools.concept_resolver import resolve as resolve_concept
    resolved = resolve_concept(term)
    if resolved:
        if resolved.codes:
            candidates.update(resolved.codes)
        elif resolved.system and resolved.code:
            candidates.add(f"{resolved.system}|{resolved.code}")

    return candidates


@mlflow.trace(name="guardrail_conflict_enforcement")
def _check_conflict(
    answer: QAAnswer,
    bundle: dict,
    inventory: BundleInventory,
) -> QAAnswer:
    """Downgrade answers based on conflicting data (same concept, different values).

    Checks all observations sharing a code with any cited observation,
    not just those in provenance. Fires on any path — resolver, plan, or agent.
    """
    if not answer.provenance:
        logger.debug("Guardrail [conflict]: skipped (no provenance)")
        return answer

    cited_obs = [
        e for e in inventory.entries
        if e.fhir_reference in answer.provenance and e.resource_type == "Observation"
    ]

    if not cited_obs:
        logger.debug("Guardrail [conflict]: skipped (no cited observations)")
        return answer

    for cited in cited_obs:
        if not cited.system or not cited.code:
            continue

        siblings = [
            e for e in inventory.entries
            if e.resource_type == "Observation"
            and e.code_token == cited.code_token
            and e.fhir_reference != cited.fhir_reference
        ]

        if not siblings:
            continue

        cited_val = _get_obs_value(cited.fhir_reference, bundle)
        for sib in siblings:
            sib_val = _get_obs_value(sib.fhir_reference, bundle)
            if cited_val is not None and sib_val is not None and abs(cited_val - sib_val) > 0.01:
                return _downgrade(
                    answer, "conflict_enforcement",
                    f"conflicting values for {cited.code_token}: "
                    f"{cited.fhir_reference}={cited_val} vs {sib.fhir_reference}={sib_val}",
                )

    logger.debug("Guardrail [conflict]: passed (no conflicting values)")
    return answer


def _get_obs_value(ref: str, bundle: dict) -> float | None:
    """Extract the numeric value from an observation by reference."""
    for resource, entry in _get_resources_with_entry(bundle, "Observation"):
        if _resource_ref(resource, entry) != ref:
            continue
        vq = resource.get("valueQuantity")
        if vq and vq.get("value") is not None:
            try:
                return float(vq["value"])
            except (ValueError, TypeError):
                pass
        for comp in resource.get("component", []):
            cvq = comp.get("valueQuantity")
            if cvq and cvq.get("value") is not None:
                try:
                    return float(cvq["value"])
                except (ValueError, TypeError):
                    pass
    return None


def check_definitive_miss(
    tool_ledger: list[dict],
    answer: QAAnswer,
) -> QAAnswer:
    """Mechanical refusal: if every resolution for the asked concept ended in
    definitive_miss and the answer claims presence, override with refusal.

    Called at the choke point AFTER verify_answer for agent-answered booleans.
    """
    if answer.insufficient_data:
        return answer

    if not isinstance(answer.value, bool):
        return answer

    if not tool_ledger:
        return answer

    all_misses = all(
        entry.get("definitive_miss", False)
        for entry in tool_ledger
        if entry.get("type") in ("check_condition", "check_medication", "check_allergy", "lookup_observation")
    )

    relevant_calls = [
        entry for entry in tool_ledger
        if entry.get("type") in ("check_condition", "check_medication", "check_allergy", "lookup_observation")
    ]

    if not relevant_calls:
        return answer

    if all_misses and answer.value is True:
        logger.info(
            "Mechanical refusal: agent claims presence but all %d tool calls returned definitive_miss",
            len(relevant_calls),
        )
        return QAAnswer(
            value=False,
            kind="boolean",
            provenance=[],
            insufficient_data=False,
            error="mechanical_refusal:definitive_miss",
            answered_by="guardrail_downgrade",
            resolution_basis="mechanical_refusal",
        )

    return answer
