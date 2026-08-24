"""Regression tests for care-plan review routing/derivation.

The UI + contract (bff-openapi.yaml) submit ReviewAction with a `decision`
field. The workflow switch and this mapper must key on `decision` — an earlier
`action` mismatch made every review fall through to the default (WriteFHIR),
so rejecting a plan silently wrote it. See CheckCarePlanReview in
acp-writer-workflow.yaml.
"""

from acp_writer.services.sonataflow_client import (
    infer_current_state,
    map_to_run_detail,
)


def test_approve_routes_to_write_fhir():
    data = {"careplanReview": {"decision": "approve", "completed_at": "2026-01-01T00:00:00Z"}}
    assert infer_current_state(data, "ACTIVE") == "WriteFHIR"


def test_request_changes_loops_back_to_generate_bundle():
    # Feedback just submitted; bundle not yet regenerated -> loop, don't write.
    data = {
        "careplanReview": {"decision": "request_changes", "completed_at": "2026-01-01T02:00:00Z"},
        "fhirGenData": {"completed_at": "2026-01-01T01:00:00Z"},
    }
    assert infer_current_state(data, "ACTIVE") == "GenerateBundle"


def test_second_round_gate_surfaces_previous_feedback():
    # request_changes, then bundle regenerated (gen newer than review) -> back at gate.
    instance = {
        "id": "run-1",
        "status": "ACTIVE",
        "startDate": "2026-01-01T00:00:00Z",
        "workflowdata": {
            "careplanReviewCount": 1,
            "careplanReview": {
                "decision": "request_changes",
                "clinician": "Dr. Smith",
                "comment": "Tighten the HbA1c target",
                "feedback": [{"itemId": "g1", "comment": "too loose"}],
                "completed_at": "2026-01-01T01:00:00Z",
            },
            "fhirGenData": {"completed_at": "2026-01-01T02:00:00Z"},
        },
    }
    detail = map_to_run_detail(instance)
    assert detail["awaitingReview"] == "careplan"
    assert detail["reviewIteration"] == 1
    assert detail["previousFeedback"] == {
        "decision": "request_changes",
        "clinician": "Dr. Smith",
        "comment": "Tighten the HbA1c target",
        "feedback": [{"itemId": "g1", "comment": "too loose"}],
    }
