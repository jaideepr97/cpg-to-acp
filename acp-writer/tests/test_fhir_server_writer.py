"""Tests for the FHIR Server Writer node and approval workflow."""

from datetime import datetime, timezone

from acp_writer.nodes.fhir_server_writer import (
    _care_plans,
    _parse_server_ids,
    approve_care_plan,
    fhir_server_writer,
    get_care_plan,
    list_care_plans,
    reject_care_plan,
)
from acp_writer.planning_brief import (
    ActivityType,
    FHIRCode,
    PlanActivity,
    PlanGoal,
    PlanningBrief,
    ReviewStatus,
    TargetValue,
)
from acp_writer.validators.fhir_bundle_builder import build_fhir_bundle

import pytest


def _sample_bundle() -> dict:
    brief = PlanningBrief(
        patient_reference="Patient/patient-1",
        applicable_cpgs=["SYN-HTN-2026-001"],
        goals=[PlanGoal(description="Lower BP", source_cpg="SYN-HTN-2026-001")],
        activities=[
            PlanActivity(
                type=ActivityType.MEDICATION,
                description="Lisinopril",
                dose="10 mg",
                source_recommendation_id="rec-1",
                source_cpg="SYN-HTN-2026-001",
            ),
        ],
        review_status=ReviewStatus.APPROVED,
    )
    return build_fhir_bundle(brief)


@pytest.fixture(autouse=True)
def clear_care_plans():
    _care_plans.clear()
    yield
    _care_plans.clear()


class TestFHIRServerWriter:
    def test_stores_locally_when_server_unavailable(self):
        state = {
            "fhir_bundle": _sample_bundle(),
            "patient_reference": "Patient/patient-1",
        }
        result = fhir_server_writer(state)
        assert result["delivery_status"] in ("stored_locally", "error", "delivered")
        assert result["careplan_id"] != ""

    def test_empty_bundle_skipped(self):
        result = fhir_server_writer({"fhir_bundle": {"entry": []}})
        assert result["delivery_status"] == "skipped"

    def test_care_plan_stored_in_memory(self):
        state = {
            "fhir_bundle": _sample_bundle(),
            "patient_reference": "Patient/patient-1",
        }
        result = fhir_server_writer(state)
        cp = get_care_plan(result["careplan_id"])
        assert cp is not None
        assert cp["patient_reference"] == "Patient/patient-1"

    def test_care_plan_has_server_ids_field(self):
        state = {
            "fhir_bundle": _sample_bundle(),
            "patient_reference": "Patient/patient-1",
        }
        result = fhir_server_writer(state)
        cp = get_care_plan(result["careplan_id"])
        assert "server_ids" in cp


class TestParseServerIds:
    def test_maps_fullurl_to_server_ref(self):
        bundle = {
            "entry": [
                {"fullUrl": "urn:uuid:aaa"},
                {"fullUrl": "urn:uuid:bbb"},
            ],
        }
        response = {
            "entry": [
                {"response": {"status": "201", "location": "Patient/123/_history/1"}},
                {"response": {"status": "201", "location": "CarePlan/456/_history/1"}},
            ],
        }
        id_map = _parse_server_ids(bundle, response)
        assert id_map["urn:uuid:aaa"] == "Patient/123"
        assert id_map["urn:uuid:bbb"] == "CarePlan/456"

    def test_empty_response(self):
        assert _parse_server_ids({"entry": []}, {}) == {}


class TestCarePlanCRUD:
    def _store_care_plan(self) -> str:
        state = {
            "fhir_bundle": _sample_bundle(),
            "patient_reference": "Patient/patient-1",
        }
        result = fhir_server_writer(state)
        return result["careplan_id"]

    def test_list_empty(self):
        assert list_care_plans() == []

    def test_list_after_store(self):
        self._store_care_plan()
        plans = list_care_plans()
        assert len(plans) == 1

    def test_list_filter_by_patient(self):
        self._store_care_plan()
        plans = list_care_plans(patient="Patient/patient-1")
        assert len(plans) == 1
        plans = list_care_plans(patient="Patient/other")
        assert len(plans) == 0

    def test_get_care_plan(self):
        cp_id = self._store_care_plan()
        cp = get_care_plan(cp_id)
        assert cp is not None
        assert cp["id"] == cp_id
        assert "bundle" in cp

    def test_get_not_found(self):
        assert get_care_plan("nonexistent") is None


class TestApprovalWorkflow:
    def _store_care_plan(self) -> str:
        state = {
            "fhir_bundle": _sample_bundle(),
            "patient_reference": "Patient/patient-1",
        }
        result = fhir_server_writer(state)
        return result["careplan_id"]

    def test_approve(self):
        cp_id = self._store_care_plan()
        result = approve_care_plan(cp_id, clinician="Dr. Smith")
        assert result["status"] == "active"

        cp = get_care_plan(cp_id)
        assert cp["status"] == "active"

        bundle = cp["bundle"]
        for entry in bundle["entry"]:
            resource = entry["resource"]
            security = resource.get("meta", {}).get("security", [])
            for sec in security:
                assert sec["code"] != "AIAST", f"AIAST should be replaced with CLINAST_AIRPT on {resource['resourceType']}"

            if resource["resourceType"] == "CarePlan":
                assert resource["status"] == "active"

    def test_approve_adds_verifier(self):
        cp_id = self._store_care_plan()
        approve_care_plan(cp_id, clinician="Dr. Smith")

        cp = get_care_plan(cp_id)
        bundle = cp["bundle"]
        for entry in bundle["entry"]:
            resource = entry["resource"]
            if resource["resourceType"] == "Provenance":
                profiles = resource.get("meta", {}).get("profile", [])
                if any("AI-Provenance" in p for p in profiles):
                    agents = resource.get("agent", [])
                    verifiers = [a for a in agents if
                                 a.get("type", {}).get("coding", [{}])[0].get("code") == "verifier"]
                    assert len(verifiers) == 1
                    assert verifiers[0]["who"]["display"] == "Dr. Smith"

    def test_reject(self):
        cp_id = self._store_care_plan()
        result = reject_care_plan(cp_id, reason="Dose too high")
        assert result["status"] == "entered-in-error"
        assert result["reason"] == "Dose too high"

        cp = get_care_plan(cp_id)
        assert cp["status"] == "entered-in-error"

        bundle = cp["bundle"]
        for entry in bundle["entry"]:
            resource = entry["resource"]
            if resource["resourceType"] == "CarePlan":
                assert resource["status"] == "entered-in-error"
                notes = [n["text"] for n in resource.get("note", [])]
                assert any("Dose too high" in n for n in notes)

    def test_approve_not_found(self):
        assert approve_care_plan("nonexistent") is None

    def test_reject_not_found(self):
        assert reject_care_plan("nonexistent", "reason") is None
