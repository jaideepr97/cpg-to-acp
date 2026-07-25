"""FHIR Server pod service — Writer + status management.

Consumes: fhir_bundle_ref.
Security profile: FHIR server access only.
"""

import logging

from fastapi import FastAPI, Request

from cpg_contracts import get_phi_store, resolve_ref
from acp_writer.nodes.fhir_server_writer import (
    approve_care_plan,
    fhir_server_writer,
    get_care_plan,
    list_care_plans,
    reject_care_plan,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="acp-writer-fhir-server", version="0.1.0")
_phi_store = get_phi_store()


@app.get("/health")
def health():
    return {"status": "UP", "service": "fhir-server"}


@app.post("/api/v1/write")
async def write(request: Request):
    """Write FHIR Bundle to HAPI FHIR server."""
    data = await request.json()
    fhir_bundle = resolve_ref(data, "fhir_bundle", _phi_store)
    state = {
        "fhir_bundle": fhir_bundle,
        "patient_reference": data.get("patient_reference", ""),
    }
    result = fhir_server_writer(state)
    return result


@app.get("/api/v1/careplans")
def careplans(patient: str | None = None, status: str | None = None):
    return list_care_plans(patient=patient, status=status)


@app.get("/api/v1/careplans/{careplan_id}")
def get_careplan(careplan_id: str):
    cp = get_care_plan(careplan_id)
    if not cp:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    return cp


@app.put("/api/v1/careplans/{careplan_id}/status")
async def update_status(careplan_id: str, request: Request):
    data = await request.json()
    new_status = data.get("status")
    if new_status == "active":
        result = approve_care_plan(careplan_id, clinician=data.get("clinician"))
    elif new_status == "entered-in-error":
        result = reject_care_plan(careplan_id, reason=data.get("reason", "No reason provided"))
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}")
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    return result
