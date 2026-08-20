"""Resolve artifact refs in run details by fetching data from MinIO.

The sonataflow_client produces a RunDetail with raw ``workflowData``;
this module hydrates ref keys into the fields the UI expects.
PHI data (IPS bundles, planning briefs, FHIR bundles) lives in the
cpg-phi bucket; non-PHI data (recommendations) in cpg-artifacts.
"""

import logging
from typing import Any

from cpg_contracts.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


def _fetch_ref(store: ArtifactStore, ref: str) -> dict | None:
    try:
        return store.get(ref)
    except Exception as exc:
        logger.warning("Could not resolve artifact ref %s: %s", ref, exc)
        return None


def _to_coded_items(codes: list | None) -> list[dict]:
    """Convert internal code lists to the contract's CodedItem[] shape."""
    if not codes:
        return []
    items = []
    for c in codes:
        if isinstance(c, dict):
            items.append({
                "display": c.get("display", c.get("name", str(c.get("code", "")))),
                "code": c.get("code", ""),
                "system": c.get("system", ""),
            })
        elif isinstance(c, str):
            items.append({"display": c})
    return items


def enrich_run_detail(
    detail: dict[str, Any],
    phi_store: ArtifactStore | None,
    artifacts_store: ArtifactStore | None,
) -> dict[str, Any]:
    """Resolve artifact refs in a RunDetail and populate UI-facing fields.

    Mutates and returns ``detail``.  The ``workflowData`` key is consumed
    and removed — it is an internal transport field, not part of the API.
    """
    wd = detail.pop("workflowData", None)
    if not wd:
        return detail

    first_error: dict[str, str] | None = None
    store = phi_store or artifacts_store

    def _record_error(step_key: str, message: str) -> None:
        nonlocal first_error
        if not first_error:
            first_error = {"stepKey": step_key, "message": message}

    # --- Patient data → PatientSummary ---
    patient_raw = wd.get("patientData") or {}
    if patient_raw:
        demographics = patient_raw.get("patient_demographics") or {}
        detail["patient"] = {
            "name": demographics.get("name", ""),
            "birthDate": demographics.get("birth_date", ""),
            "gender": demographics.get("gender", ""),
            "patientReference": patient_raw.get("patient_reference", ""),
            "conditions": _to_coded_items(patient_raw.get("condition_codes")),
            "medications": _to_coded_items(patient_raw.get("medication_codes")),
            "allergies": _to_coded_items(patient_raw.get("allergy_codes")),
            "observations": _to_coded_items(patient_raw.get("observation_codes")),
        }

    # --- DMN results ---
    dmn_raw = wd.get("dmnData") or {}
    if "error" in dmn_raw:
        _record_error("execute_dmn", str(dmn_raw["error"]))

    # --- Recommendations ---
    rec_raw = wd.get("recData") or {}
    if "error" in rec_raw:
        _record_error("retrieve_recommendations", str(rec_raw["error"]))

    # --- Planning brief (from ComposePlan) → CarePlanView source ---
    composer_raw = wd.get("composerData") or {}
    planning_brief = None
    if "error" in composer_raw:
        _record_error("compose_plan", str(composer_raw["error"]))
    elif composer_raw:
        brief = composer_raw
        ref = composer_raw.get("planning_brief_ref")
        if ref and phi_store:
            resolved = _fetch_ref(phi_store, ref)
            if resolved:
                brief = resolved
        planning_brief = brief.get("planning_brief", brief)

    # --- FHIR generation → CarePlanView ---
    fhir_gen_raw = wd.get("fhirGenData") or {}
    if "error" in fhir_gen_raw:
        _record_error("generate_bundle", str(fhir_gen_raw["error"]))
    elif fhir_gen_raw:
        bundle = fhir_gen_raw
        ref = fhir_gen_raw.get("fhir_bundle_ref")
        if ref and phi_store:
            resolved = _fetch_ref(phi_store, ref)
            if resolved:
                bundle = resolved
        fhir_bundle = bundle.get("fhir_bundle", bundle)

        care_plan_view: dict[str, Any] = {"fhirBundle": fhir_bundle}
        if planning_brief and isinstance(planning_brief, dict):
            care_plan_view["goals"] = planning_brief.get("goals", [])
            care_plan_view["activities"] = planning_brief.get("activities", [])
            care_plan_view["conflicts"] = planning_brief.get("conflicts", [])
        detail["carePlan"] = care_plan_view

    # --- Write result ---
    write_raw = wd.get("writeResult") or {}
    if "error" in write_raw:
        _record_error("write_fhir", str(write_raw["error"]))
    elif write_raw:
        detail["careplanId"] = write_raw.get("careplan_id")

    if first_error:
        detail["error"] = first_error

    return detail
