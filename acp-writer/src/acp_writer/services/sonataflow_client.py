"""SonataFlow REST/GraphQL client and workflow state mapping for the acp-writer BFF."""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import requests

logger = logging.getLogger(__name__)

WORKFLOW_NAME = "acpwriter"

PIPELINE_STEPS = [
    "ScanPatient", "ResolveGuidelines", "ExecuteDMN", "RetrieveRecommendations",
    "ComposePlan",
    "GenerateBundle", "ReviewFHIR", "ReviewCarePlan",
    "WriteFHIR", "Done",
]

_STEP_KEY = {
    "ScanPatient": "scan_patient",
    "ResolveGuidelines": "resolve_guidelines",
    "ExecuteDMN": "execute_dmn",
    "RetrieveRecommendations": "retrieve_recommendations",
    "ComposePlan": "compose_plan",
    "GenerateBundle": "generate_bundle",
    "ReviewFHIR": "review_fhir",
    "ReviewCarePlan": "review_careplan",
    "WriteFHIR": "write_fhir",
    "Done": "done",
}

_STATE_TO_RUN_STATUS = {
    "ScanPatient": "running",
    "ResolveGuidelines": "running",
    "ExecuteDMN": "running",
    "RetrieveRecommendations": "running",
    "ComposePlan": "running",
    "GenerateBundle": "running",
    "ReviewFHIR": "running",
    "ReviewCarePlan": "awaiting_careplan_review",
    "WriteFHIR": "running",
    "Done": "completed",
    "Failed": "failed",
    "Aborted": "cancelled",
}

_REVIEW_GATE_MAP = {
    "ReviewCarePlan": "careplan",
}

_REVIEW_EVENT_TYPE = {
    "careplan": "careplan-reviewed",
}

_REVIEW_WAIT_PATH = {
    "careplan": "wait-careplan-review",
}


def infer_current_state(data: dict, instance_status: str) -> str:
    """Determine the active pipeline step from workflow data.

    Walks result keys in reverse pipeline order. Each key's presence
    indicates that step has completed; the first missing key is active.
    """
    if instance_status == "COMPLETED" or data.get("status") == "completed":
        return "Done"
    if instance_status == "ABORTED":
        return "Aborted"
    if instance_status == "ERROR":
        return "Failed"

    if "writeResult" in data:
        return "Done"

    careplan_review = data.get("careplanReview", {})
    if careplan_review.get("action") == "approve":
        return "WriteFHIR"
    if careplan_review.get("action") == "request_changes":
        review_at = careplan_review.get("completed_at", "")
        gen_at = data.get("fhirGenData", {}).get("completed_at", "")
        if gen_at and gen_at > review_at:
            return "ReviewCarePlan"
        return "GenerateBundle"

    if "fhirReviewData" in data:
        return "ReviewCarePlan"
    if "fhirGenData" in data:
        return "ReviewFHIR"
    if "composerData" in data:
        return "GenerateBundle"
    if "recData" in data:
        return "ComposePlan"
    if "dmnData" in data:
        return "RetrieveRecommendations"
    if "guidelineData" in data:
        return "ExecuteDMN"
    if "patientData" in data:
        return "ResolveGuidelines"
    return "ScanPatient"


def _step_timestamps(data: dict, created_at: str) -> dict[str, dict[str, str]]:
    """Build step name -> {startedAt, endedAt} from result timestamps."""
    timestamps: dict[str, dict[str, str]] = {}
    prev = created_at

    step_result_keys = [
        ("ScanPatient", "patientData"),
        ("ResolveGuidelines", "guidelineData"),
        ("ExecuteDMN", "dmnData"),
        ("RetrieveRecommendations", "recData"),
        ("ComposePlan", "composerData"),
        ("GenerateBundle", "fhirGenData"),
        ("ReviewFHIR", "fhirReviewData"),
        ("ReviewCarePlan", "careplanReview"),
        ("WriteFHIR", "writeResult"),
    ]

    for step_name, result_key in step_result_keys:
        result = data.get(result_key)
        if not result or not isinstance(result, dict):
            if prev:
                timestamps[step_name] = {"startedAt": prev}
            break
        completed = result.get("completed_at", "")
        entry: dict[str, str] = {}
        if prev:
            entry["startedAt"] = prev
        if completed:
            entry["endedAt"] = completed
        timestamps[step_name] = entry
        prev = completed or prev

    if data.get("status") == "completed" or "writeResult" in data:
        write = data.get("writeResult", {})
        done_at = write.get("completed_at", "")
        if done_at:
            timestamps["Done"] = {"startedAt": done_at, "endedAt": done_at}

    return timestamps


def build_steps(current_state: str, data: dict | None = None, created_at: str = "") -> list[dict]:
    """Build the steps array the UI PipelineStepper expects."""
    ts = _step_timestamps(data or {}, created_at) if data else {}
    d = data or {}
    careplan_count = d.get("careplanReviewCount", 0) or 0
    in_careplan_loop = current_state in ("GenerateBundle", "ReviewFHIR", "ReviewCarePlan") and careplan_count > 0

    steps = []
    reached = False
    for name in PIPELINE_STEPS:
        key = _STEP_KEY[name]
        if name == current_state:
            reached = True
            step: dict = {"key": key, "status": "active"}
        elif not reached:
            step = {"key": key, "status": "done"}
        else:
            step = {"key": key, "status": "pending"}

        if name in ts:
            step.update(ts[name])

        if name in ("GenerateBundle", "ReviewFHIR", "ReviewCarePlan"):
            if in_careplan_loop:
                step["iteration"] = careplan_count + 1
            elif careplan_count > 1:
                step["iteration"] = careplan_count

        steps.append(step)

    if current_state == "Done":
        for s in steps:
            s["status"] = "done"
    if current_state == "Failed":
        for s in steps:
            if s["status"] == "active":
                s["status"] = "error"
                break
    return steps


def map_to_run_summary(instance: dict) -> dict[str, Any]:
    """Map a SonataFlow workflow instance to a RunSummary for the dashboard."""
    data = instance.get("workflowdata", {})
    status = instance.get("status", "ACTIVE")
    current_state = infer_current_state(data, status)
    patient = data.get("patientData", {}).get("patient_demographics", {})
    patient_name = patient.get("name", "Unknown Patient") if patient else "Unknown Patient"
    patient_ref = data.get("patientData", {}).get("patient_reference", "")
    write_result = data.get("writeResult", {})
    start_date = instance.get("startDate") or data.get("created_at", "")
    return {
        "runId": instance["id"],
        "status": _STATE_TO_RUN_STATUS.get(current_state, "running"),
        "patientName": patient_name,
        "patientReference": patient_ref,
        "currentSteps": [_STEP_KEY.get(current_state, "scan_patient")],
        "careplanId": write_result.get("careplan_id") if write_result else None,
        "createdAt": start_date,
        "updatedAt": instance.get("endDate") or start_date,
    }


def map_to_run_detail(instance: dict) -> dict[str, Any]:
    """Map a SonataFlow workflow instance to a RunDetail for the detail view.

    Returns workflow data as-is — artifact refs are NOT resolved here.
    Use ``artifact_resolver.enrich_run_detail`` to hydrate refs from MinIO.
    """
    data = instance.get("workflowdata", {})
    status = instance.get("status", "ACTIVE")
    current_state = infer_current_state(data, status)

    patient = data.get("patientData", {}).get("patient_demographics", {})
    patient_name = patient.get("name", "Unknown Patient") if patient else "Unknown Patient"
    created_at = instance.get("startDate") or data.get("created_at", "")

    detail: dict[str, Any] = {
        "runId": instance["id"],
        "status": _STATE_TO_RUN_STATUS.get(current_state, "running"),
        "createdAt": created_at,
        "updatedAt": instance.get("endDate") or created_at,
        "currentSteps": [_STEP_KEY.get(current_state, "scan_patient")],
        "steps": build_steps(current_state, data, created_at),
        "awaitingReview": None,
        "carePlan": None,
        "reviewIteration": 0,
        "previousFeedback": None,
        "careplanId": None,
        "error": None,
        "workflowData": {
            "patientData": data.get("patientData"),
            "guidelineData": data.get("guidelineData"),
            "dmnData": data.get("dmnData"),
            "recData": data.get("recData"),
            "composerData": data.get("composerData"),
            "fhirGenData": data.get("fhirGenData"),
            "fhirReviewData": data.get("fhirReviewData"),
            "writeResult": data.get("writeResult"),
        },
    }

    if current_state == "ReviewCarePlan":
        detail["awaitingReview"] = "careplan"
        detail["reviewIteration"] = data.get("careplanReviewCount", 0)
        prev = data.get("careplanReview")
        if prev and prev.get("action") == "request_changes":
            detail["previousFeedback"] = {
                "decision": "request_changes",
                "clinician": prev.get("clinician"),
                "comment": prev.get("comment"),
                "feedback": prev.get("feedback", []),
            }

    return detail


_GRAPHQL_LIST = """
query {
  ProcessInstances(where: {processId: {equal: "%s"}}, orderBy: {start: DESC}) {
    id state start end variables
  }
}
""" % WORKFLOW_NAME

_GRAPHQL_GET = """
query ($id: String!) {
  ProcessInstances(where: {id: {equal: $id}}) {
    id state start end variables
  }
}
"""


def _graphql_to_instance(pi: dict) -> dict:
    """Normalize a GraphQL ProcessInstance to match REST API shape."""
    variables = pi.get("variables") or {}
    if isinstance(variables, str):
        import json as _json
        variables = _json.loads(variables)
    return {
        "id": pi["id"],
        "status": pi["state"],
        "startDate": pi.get("start", ""),
        "endDate": pi.get("end", ""),
        "workflowdata": variables.get("workflowdata", {}),
    }


class SonataFlowClient:
    """Client for the SonataFlow acpwriter workflow.

    Uses GraphQL (embedded Data Index) for queries so completed instances
    are included.  Uses REST for mutations (start, abort, send review).
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _graphql(self, query: str, variables: dict | None = None) -> dict:
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = requests.post(
            f"{self.base_url}/graphql",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def start_workflow(self, ips_ref: str, patient_name: str) -> dict:
        resp = requests.post(
            f"{self.base_url}/{WORKFLOW_NAME}",
            json={
                "ips_ref": ips_ref,
                "patient_name": patient_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            headers={"Content-Type": "application/json"},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def list_instances(self) -> list[dict]:
        result = self._graphql(_GRAPHQL_LIST)
        instances = result.get("data", {}).get("ProcessInstances", [])
        return [_graphql_to_instance(pi) for pi in instances]

    def get_instance(self, instance_id: str) -> dict:
        result = self._graphql(_GRAPHQL_GET, {"id": instance_id})
        instances = result.get("data", {}).get("ProcessInstances", [])
        if not instances:
            raise requests.HTTPError(
                f"Run {instance_id} not found", response=type("R", (), {"status_code": 404})()
            )
        return _graphql_to_instance(instances[0])

    def abort_instance(self, instance_id: str) -> None:
        resp = requests.delete(
            f"{self.base_url}/{WORKFLOW_NAME}/{instance_id}",
            timeout=10,
        )
        resp.raise_for_status()

    def send_review(self, instance_id: str, gate: str, review_data: dict) -> None:
        event_type = _REVIEW_EVENT_TYPE[gate]
        wait_path = _REVIEW_WAIT_PATH[gate]
        review_data.setdefault("completed_at", datetime.now(timezone.utc).isoformat())
        cloud_event = {
            "specversion": "1.0",
            "id": str(uuid4()),
            "source": "bff",
            "type": event_type,
            "kogitoprocrefid": instance_id,
            "data": review_data,
        }
        resp = requests.post(
            f"{self.base_url}/{wait_path}",
            json=cloud_event,
            headers={"Content-Type": "application/cloudevents+json"},
            timeout=60,
        )
        resp.raise_for_status()
