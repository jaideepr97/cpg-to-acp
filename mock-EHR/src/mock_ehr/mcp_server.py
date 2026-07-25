"""MCP server exposing FHIR patient data queries via the Model Context Protocol."""

import json
import os

import mlflow
import requests
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from cpg_contracts import PatientSummary

mcp = FastMCP(
    "mock-ehr-fhir",
    host="0.0.0.0",
    port=8090,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

FHIR_BASE_URL = os.environ.get("FHIR_BASE_URL", "http://localhost:8080/fhir")


def _fhir_get(path: str) -> dict:
    r = requests.get(f"{FHIR_BASE_URL}/{path}", timeout=10)
    r.raise_for_status()
    return r.json()


@mcp.tool()
@mlflow.trace(name="fhir_get_patient_summary")
def get_patient_summary(patient_id: str) -> str:
    """Retrieve a patient summary including demographics, conditions, observations, and medications."""
    patient = _fhir_get(f"Patient/{patient_id}")

    conditions_bundle = _fhir_get(f"Condition?patient={patient_id}")
    conditions = [e["resource"] for e in conditions_bundle.get("entry", [])]

    obs_bundle = _fhir_get(f"Observation?patient={patient_id}")
    observations = [e["resource"] for e in obs_bundle.get("entry", [])]

    med_bundle = _fhir_get(f"MedicationStatement?patient={patient_id}")
    medications = [e["resource"] for e in med_bundle.get("entry", [])]

    name = patient.get("name", [{}])[0]
    summary = PatientSummary(
        patient_id=patient_id,
        name=f"{name.get('given', [''])[0]} {name.get('family', '')}",
        birth_date=patient.get("birthDate"),
        gender=patient.get("gender"),
        conditions=conditions,
        observations=observations,
        medications=medications,
    )
    return json.dumps(summary.model_dump(mode="json"))


@mcp.tool()
@mlflow.trace(name="fhir_get_patient_conditions")
def get_patient_conditions(patient_id: str) -> str:
    """Query active conditions for a patient."""
    bundle = _fhir_get(f"Condition?patient={patient_id}")
    conditions = [e["resource"] for e in bundle.get("entry", [])]
    return json.dumps(conditions)


@mcp.tool()
@mlflow.trace(name="fhir_get_patient_observations")
def get_patient_observations(patient_id: str, code: str = "") -> str:
    """Query observations for a patient, optionally filtered by LOINC code."""
    path = f"Observation?patient={patient_id}"
    if code:
        path += f"&code={code}"
    bundle = _fhir_get(path)
    observations = [e["resource"] for e in bundle.get("entry", [])]
    return json.dumps(observations)


@mcp.tool()
@mlflow.trace(name="fhir_list_patients")
def list_patients() -> str:
    """List all patients in the FHIR server."""
    bundle = _fhir_get("Patient")
    patients = []
    for entry in bundle.get("entry", []):
        p = entry["resource"]
        name = p.get("name", [{}])[0]
        patients.append({
            "id": p.get("id"),
            "name": f"{name.get('given', [''])[0]} {name.get('family', '')}",
            "birthDate": p.get("birthDate"),
            "gender": p.get("gender"),
        })
    return json.dumps(patients)
