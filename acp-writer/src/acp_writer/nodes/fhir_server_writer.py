"""FHIR Server Writer — POST transaction Bundle to HAPI FHIR server.

Validates OperationOutcome response and stores care plan reference.
Supports approve/reject workflow with AI Transparency tag transitions.
Care plans are POSTed as "draft" and updated to "active" or
"entered-in-error" on the server on approve/reject.
"""

import json
import logging
import os
import uuid

import mlflow
import requests

from acp_writer.output import write_artifact
from acp_writer.state import CarePlanComposerState

logger = logging.getLogger(__name__)

FHIR_SERVER_URL = os.environ.get("FHIR_SERVER_URL", "http://localhost:8080/fhir")

_care_plans: dict[str, dict] = {}


def _parse_server_ids(bundle: dict, response_data: dict) -> dict[str, str]:
    """Map urn:uuid: fullUrls to server-assigned IDs from a transaction response."""
    id_map: dict[str, str] = {}
    request_entries = bundle.get("entry", [])
    response_entries = response_data.get("entry", [])
    for req_entry, resp_entry in zip(request_entries, response_entries):
        full_url = req_entry.get("fullUrl", "")
        location = resp_entry.get("response", {}).get("location", "")
        if full_url and location:
            parts = location.split("/")
            if len(parts) >= 2:
                server_ref = f"{parts[0]}/{parts[1]}"
                id_map[full_url] = server_ref
    return id_map


def _find_careplan_server_id(id_map: dict[str, str]) -> str | None:
    """Find the server-assigned CarePlan reference from the ID map."""
    for urn, server_ref in id_map.items():
        if server_ref.startswith("CarePlan/"):
            return server_ref
    return None


def _update_on_server(server_ref: str, resource: dict) -> bool:
    """PUT an updated resource to the FHIR server. Returns True on success."""
    url = f"{FHIR_SERVER_URL}/{server_ref}"
    try:
        r = requests.put(
            url,
            json=resource,
            headers={"Content-Type": "application/fhir+json"},
            timeout=30,
        )
        if r.status_code in (200, 201):
            logger.info("Updated %s on FHIR server", server_ref)
            return True
        else:
            logger.warning("FHIR server PUT %s returned %d: %s", server_ref, r.status_code, r.text[:200])
            return False
    except requests.RequestException as e:
        logger.warning("FHIR server unavailable for PUT %s: %s", server_ref, e)
        return False


@mlflow.trace(name="fhir_server_writer")
def fhir_server_writer(state: CarePlanComposerState) -> dict:
    """Write the FHIR Bundle to the HAPI FHIR server."""
    logger.info("── FHIR Server Writer ──")
    bundle = state.get("fhir_bundle", {})
    output_dir = state.get("output_dir", "")

    if not bundle.get("entry"):
        logger.info("Empty FHIR bundle — skipping server write")
        return {"delivery_status": "skipped", "careplan_id": ""}

    careplan_id = str(uuid.uuid4())

    _care_plans[careplan_id] = {
        "id": careplan_id,
        "bundle": bundle,
        "status": "draft",
        "patient_reference": state.get("patient_reference", ""),
        "server_ids": {},
    }

    try:
        r = requests.post(
            FHIR_SERVER_URL,
            json=bundle,
            headers={"Content-Type": "application/fhir+json"},
            timeout=30,
        )

        response_data = r.json() if r.content else {}

        if r.status_code in (200, 201):
            logger.info("FHIR Bundle posted successfully (status %d)", r.status_code)
            server_ids = _parse_server_ids(bundle, response_data)
            _care_plans[careplan_id]["fhir_response"] = response_data
            _care_plans[careplan_id]["server_ids"] = server_ids

            if output_dir:
                write_artifact(output_dir, "fhir-server-response.json", response_data)

            return {
                "fhir_server_response": response_data,
                "careplan_id": careplan_id,
                "delivery_status": "delivered",
            }
        else:
            logger.warning("FHIR server returned %d: %s", r.status_code, r.text[:200])
            _care_plans[careplan_id]["error"] = r.text[:500]
            return {
                "fhir_server_response": response_data,
                "careplan_id": careplan_id,
                "delivery_status": "error",
            }

    except requests.RequestException as e:
        logger.warning("FHIR server unavailable: %s — storing locally only", e)
        return {
            "fhir_server_response": {},
            "careplan_id": careplan_id,
            "delivery_status": "stored_locally",
        }


def get_care_plan(careplan_id: str) -> dict | None:
    return _care_plans.get(careplan_id)


def list_care_plans(patient: str | None = None, status: str | None = None) -> list[dict]:
    results = list(_care_plans.values())
    if patient:
        results = [cp for cp in results if cp.get("patient_reference") == patient]
    if status:
        results = [cp for cp in results if cp.get("status") == status]
    return [{
        "id": cp["id"],
        "patient_reference": cp.get("patient_reference", ""),
        "status": cp.get("status", ""),
    } for cp in results]


CLINAST_AIRPT_SECURITY = {
    "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
    "code": "CLINAST_AIRPT",
    "display": "clinician asserted from AI reported",
}


def approve_care_plan(careplan_id: str, clinician: str | None = None) -> dict | None:
    """Approve a care plan: status→active, AIAST→CLINAST_AIRPT, update on FHIR server."""
    cp = _care_plans.get(careplan_id)
    if not cp:
        return None

    cp["status"] = "active"
    bundle = cp.get("bundle", {})

    careplan_resource = None
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        security = resource.get("meta", {}).get("security", [])
        for i, sec in enumerate(security):
            if sec.get("code") == "AIAST":
                security[i] = CLINAST_AIRPT_SECURITY

        if resource.get("resourceType") == "CarePlan":
            resource["status"] = "active"
            careplan_resource = resource

        if resource.get("resourceType") == "Provenance":
            profiles = resource.get("meta", {}).get("profile", [])
            if any("AI-Provenance" in p for p in profiles):
                agents = resource.get("agent", [])
                agents.append({
                    "type": {
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                            "code": "verifier",
                        }],
                    },
                    "who": {"display": clinician or "Clinician"},
                })

    server_ref = _find_careplan_server_id(cp.get("server_ids", {}))
    if server_ref and careplan_resource:
        _update_on_server(server_ref, careplan_resource)
    elif careplan_resource:
        logger.info("No server ID for CarePlan — server-side update skipped (local only)")

    return {"id": careplan_id, "status": "active"}


def reject_care_plan(careplan_id: str, reason: str) -> dict | None:
    """Reject a care plan: status→entered-in-error, update on FHIR server."""
    cp = _care_plans.get(careplan_id)
    if not cp:
        return None

    cp["status"] = "entered-in-error"
    bundle = cp.get("bundle", {})

    careplan_resource = None
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "CarePlan":
            resource["status"] = "entered-in-error"
            notes = resource.get("note", [])
            notes.append({"text": f"Rejected: {reason}"})
            resource["note"] = notes
            careplan_resource = resource

    server_ref = _find_careplan_server_id(cp.get("server_ids", {}))
    if server_ref and careplan_resource:
        _update_on_server(server_ref, careplan_resource)
    elif careplan_resource:
        logger.info("No server ID for CarePlan — server-side update skipped (local only)")

    return {"id": careplan_id, "status": "entered-in-error", "reason": reason}
