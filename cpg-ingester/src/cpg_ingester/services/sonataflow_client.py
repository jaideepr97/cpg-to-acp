"""SonataFlow REST client and workflow state mapping for the BFF."""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import requests

logger = logging.getLogger(__name__)

WORKFLOW_NAME = "cpgingester"

PIPELINE_STEPS = [
    "Parse", "Analyze", "ReviewManifest",
    "Generate", "ReviewArtifacts",
    "Assemble", "Deliver", "Done",
]

_STATE_TO_RUN_STATUS = {
    "Parse": "parsing",
    "Analyze": "analyzing",
    "ReviewManifest": "awaiting_manifest_review",
    "Generate": "generating",
    "ReviewArtifacts": "awaiting_artifact_review",
    "Assemble": "assembling",
    "Deliver": "delivering",
    "Done": "completed",
}

_REVIEW_GATE_MAP = {
    "ReviewManifest": "manifest",
    "ReviewArtifacts": "pre-delivery",
}

_REVIEW_EVENT_TYPE = {
    "manifest": "manifest-reviewed",
    "pre-delivery": "artifacts-reviewed",
}

_REVIEW_WAIT_PATH = {
    "manifest": "wait-manifest-review",
    "pre-delivery": "wait-artifact-review",
}


def infer_current_state(data: dict, instance_status: str) -> str:
    """Determine the active pipeline step from workflow data."""
    if instance_status == "COMPLETED" or data.get("status") == "completed":
        return "Done"
    if instance_status in ("ERROR", "ABORTED"):
        return "Failed"

    if "deliveryResult" in data:
        return "Done"
    if "assemblyResult" in data:
        return "Deliver"
    if data.get("artifactsReview", {}).get("action") == "approve":
        return "Assemble"
    if "generateResult" in data:
        return "ReviewArtifacts"
    if data.get("manifestReview", {}).get("action") == "approve":
        return "Generate"
    if "analysisResult" in data:
        return "ReviewManifest"
    if "parseResult" in data:
        return "Analyze"
    return "Parse"


def build_steps(current_state: str) -> list[dict[str, str]]:
    """Build the steps array the UI expects from the current state."""
    steps = []
    reached = False
    for name in PIPELINE_STEPS:
        if name == current_state:
            reached = True
            steps.append({"name": name, "status": "active"})
        elif not reached:
            steps.append({"name": name, "status": "completed"})
        else:
            steps.append({"name": name, "status": "pending"})
    if current_state == "Done":
        for s in steps:
            s["status"] = "completed"
    if current_state == "Failed":
        for s in steps:
            if s["status"] == "active":
                s["status"] = "failed"
                break
    return steps


def map_to_run_summary(instance: dict) -> dict[str, Any]:
    """Map a SonataFlow workflow instance to a RunSummary for the dashboard."""
    data = instance.get("workflowdata", {})
    status = instance.get("status", "ACTIVE")
    current_state = infer_current_state(data, status)
    return {
        "id": instance["id"],
        "status": _STATE_TO_RUN_STATUS.get(current_state, "parsing"),
        "cpgName": data.get("cpg_name", "Unknown CPG"),
        "createdAt": instance.get("startDate") or data.get("created_at", ""),
        "currentStep": current_state,
    }


def map_to_run_detail(instance: dict) -> dict[str, Any]:
    """Map a SonataFlow workflow instance to a RunDetail for the detail view.

    Returns workflow data as-is — artifact refs are NOT resolved here.
    Use ``artifact_resolver.enrich_run_detail`` to hydrate refs from MinIO.
    """
    data = instance.get("workflowdata", {})
    status = instance.get("status", "ACTIVE")
    current_state = infer_current_state(data, status)

    detail: dict[str, Any] = {
        "id": instance["id"],
        "status": _STATE_TO_RUN_STATUS.get(current_state, "parsing"),
        "cpgName": data.get("cpg_name", "Unknown CPG"),
        "createdAt": instance.get("startDate") or data.get("created_at", ""),
        "steps": build_steps(current_state),
        "workflowData": {
            "analysisResult": data.get("analysisResult"),
            "generateResult": data.get("generateResult"),
            "assemblyResult": data.get("assemblyResult"),
            "deliveryResult": data.get("deliveryResult"),
        },
    }

    review_type = _REVIEW_GATE_MAP.get(current_state)
    if review_type:
        detail["awaitingReview"] = review_type

    if current_state == "ReviewManifest":
        detail["reviewIteration"] = data.get("manifestReviewCount", 0)
        prev = data.get("manifestReview")
        if prev and prev.get("action") == "request_changes":
            detail["previousFeedback"] = prev
    elif current_state == "ReviewArtifacts":
        detail["reviewIteration"] = data.get("artifactReviewCount", 0)
        prev = data.get("artifactsReview")
        if prev and prev.get("action") == "request_changes":
            detail["previousFeedback"] = prev

    return detail


class SonataFlowClient:
    """REST client for the SonataFlow cpgingester workflow."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def start_workflow(self, pdf_ref: str, cpg_name: str) -> dict:
        resp = requests.post(
            f"{self.base_url}/{WORKFLOW_NAME}",
            json={
                "pdf_ref": pdf_ref,
                "cpg_name": cpg_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def list_instances(self) -> list[dict]:
        resp = requests.get(
            f"{self.base_url}/{WORKFLOW_NAME}",
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_instance(self, instance_id: str) -> dict:
        resp = requests.get(
            f"{self.base_url}/{WORKFLOW_NAME}/{instance_id}",
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def abort_instance(self, instance_id: str) -> None:
        resp = requests.delete(
            f"{self.base_url}/{WORKFLOW_NAME}/{instance_id}",
            timeout=10,
        )
        resp.raise_for_status()

    def send_review(self, instance_id: str, gate: str, review_data: dict) -> None:
        event_type = _REVIEW_EVENT_TYPE[gate]
        wait_path = _REVIEW_WAIT_PATH[gate]
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
            timeout=10,
        )
        resp.raise_for_status()
