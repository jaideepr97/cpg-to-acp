"""Condition Scanner — extract patient condition codes from IPS Bundle.

Deterministic FHIR traversal, no LLM. Extracts active conditions,
medications, and allergies for downstream guideline matching.
"""

import logging
from typing import Any

import mlflow

from acp_writer.state import CarePlanComposerState

logger = logging.getLogger(__name__)

CLINICAL_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"


def _get_resources(bundle: dict, resource_type: str) -> list[dict]:
    return [
        e["resource"]
        for e in bundle.get("entry", [])
        if e.get("resource", {}).get("resourceType") == resource_type
    ]


def _extract_codings(codeable_concept: dict | None) -> list[dict[str, str]]:
    if not codeable_concept:
        return []
    result = []
    for coding in codeable_concept.get("coding", []):
        entry = {
            "system": coding.get("system", ""),
            "code": coding.get("code", ""),
        }
        if coding.get("display"):
            entry["display"] = coding["display"]
        result.append(entry)
    return result


def _is_active_status(resource: dict, status_field: str = "clinicalStatus") -> bool:
    status_cc = resource.get(status_field)
    if not status_cc:
        return True
    for coding in status_cc.get("coding", []):
        if coding.get("code") in ("active", "recurrence", "relapse"):
            return True
    return False


def _extract_patient_demographics(patient: dict) -> dict[str, Any]:
    demographics: dict[str, Any] = {
        "id": patient.get("id", ""),
        "reference": f"Patient/{patient.get('id', '')}",
    }
    if patient.get("gender"):
        demographics["gender"] = patient["gender"]
    if patient.get("birthDate"):
        demographics["birth_date"] = patient["birthDate"]
    names = patient.get("name", [])
    if names:
        name = names[0]
        given = " ".join(name.get("given", []))
        family = name.get("family", "")
        demographics["name"] = f"{given} {family}".strip()
    identifiers = patient.get("identifier", [])
    if identifiers:
        demographics["identifiers"] = [
            {"system": ident.get("system", ""), "value": ident.get("value", "")}
            for ident in identifiers
            if ident.get("value")
        ]
    return demographics


@mlflow.trace(name="condition_scanner")
def condition_scanner(state: CarePlanComposerState) -> dict:
    """Extract condition codes, medication codes, and demographics from IPS."""
    logger.info("── Condition Scanner ──")
    bundle = state.get("ips_bundle", {})
    if not bundle:
        logger.warning("No IPS bundle provided")
        return {}

    patients = _get_resources(bundle, "Patient")
    if not patients:
        logger.warning("No Patient resource in bundle")
        return {}
    patient = patients[0]
    demographics = _extract_patient_demographics(patient)
    patient_ref = demographics["reference"]
    logger.info("Patient: %s (%s)", demographics.get("name", "unknown"), patient_ref)

    condition_codes = []
    for condition in _get_resources(bundle, "Condition"):
        if not _is_active_status(condition):
            continue
        codes = _extract_codings(condition.get("code"))
        if codes:
            condition_codes.extend(codes)

    medication_codes = []
    for med_stmt in _get_resources(bundle, "MedicationStatement"):
        if med_stmt.get("status") not in ("active", "intended", "completed", None):
            continue
        codes = _extract_codings(med_stmt.get("medicationCodeableConcept"))
        if codes:
            medication_codes.extend(codes)
    for med_req in _get_resources(bundle, "MedicationRequest"):
        if med_req.get("status") in ("cancelled", "entered-in-error", "stopped"):
            continue
        codes = _extract_codings(med_req.get("medicationCodeableConcept"))
        if codes:
            medication_codes.extend(codes)

    allergy_codes = []
    for allergy in _get_resources(bundle, "AllergyIntolerance"):
        if not _is_active_status(allergy):
            continue
        codes = _extract_codings(allergy.get("code"))
        if codes:
            allergy_codes.extend(codes)

    logger.info(
        "Scanned: %d conditions, %d medications, %d allergies",
        len(condition_codes),
        len(medication_codes),
        len(allergy_codes),
    )

    return {
        "patient_reference": patient_ref,
        "patient_demographics": demographics,
        "condition_codes": condition_codes,
        "medication_codes": medication_codes,
        "allergy_codes": allergy_codes,
    }
