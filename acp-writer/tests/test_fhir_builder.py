"""Tests for the deterministic FHIR Bundle builder."""

import json
from datetime import datetime, timezone

from acp_writer.planning_brief import (
    ActivityType,
    ActivityWorkflow,
    DMNAuditEntry,
    FHIRCode,
    PlanActivity,
    PlanGoal,
    PlanningBrief,
    ReviewStatus,
    TargetValue,
)
from acp_writer.validators.fhir_bundle_builder import AIAST_SECURITY, build_fhir_bundle


def _hypertension_brief() -> PlanningBrief:
    return PlanningBrief(
        patient_reference="Patient/patient-1",
        applicable_cpgs=["SYN-HTN-2026-001"],
        dmn_audit_trail=[
            DMNAuditEntry(
                model_id="treatment-recommendation",
                model_name="Treatment Recommendation",
                inputs={"Systolic BP": 142},
                outputs={"Action": "Start medication", "Medication": "Lisinopril"},
                timestamp=datetime(2026, 7, 21, 10, 0, 0, tzinfo=timezone.utc),
            ),
        ],
        goals=[
            PlanGoal(
                description="Lower blood pressure to target range",
                target_measure_code=FHIRCode(system="http://loinc.org", code="8480-6", display="Systolic BP"),
                target_value=TargetValue(high=140, unit="mmHg"),
                source_recommendation_id="rec-123",
                source_cpg="SYN-HTN-2026-001",
            ),
        ],
        activities=[
            PlanActivity(
                type=ActivityType.MEDICATION,
                description="Start Lisinopril 10mg daily",
                code=FHIRCode(system="http://www.nlm.nih.gov/research/umls/rxnorm", code="29046", display="Lisinopril"),
                dose="10 mg",
                route="oral",
                frequency="daily",
                source_recommendation_id="rec-456",
                source_cpg="SYN-HTN-2026-001",
                source_dmn_call=0,
                workflow=ActivityWorkflow(actor="prescribing_physician"),
            ),
            PlanActivity(
                type=ActivityType.MONITORING,
                description="Basic Metabolic Panel",
                code=FHIRCode(system="http://loinc.org", code="51990-0", display="Basic metabolic panel"),
                frequency="4 weeks",
                source_recommendation_id="rec-789",
                source_cpg="SYN-HTN-2026-001",
            ),
            PlanActivity(
                type=ActivityType.LIFESTYLE,
                description="DASH diet - reduce sodium intake",
                source_recommendation_id="rec-abc",
                source_cpg="SYN-HTN-2026-001",
            ),
        ],
        review_status=ReviewStatus.APPROVED,
    )


def _get_resources(bundle: dict, resource_type: str) -> list[dict]:
    return [
        e["resource"]
        for e in bundle.get("entry", [])
        if e.get("resource", {}).get("resourceType") == resource_type
    ]


class TestBundleStructure:
    def test_is_transaction_bundle(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "transaction"
        assert bundle.get("timestamp") is not None

    def test_all_entries_have_request(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        for entry in bundle["entry"]:
            assert "request" in entry
            assert entry["request"]["method"] == "POST"

    def test_all_entries_have_fullurl(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        for entry in bundle["entry"]:
            assert entry["fullUrl"].startswith("urn:uuid:")

    def test_json_serializable(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        json_str = json.dumps(bundle)
        restored = json.loads(json_str)
        assert restored["resourceType"] == "Bundle"


class TestCarePlan:
    def test_careplan_present(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        careplans = _get_resources(bundle, "CarePlan")
        assert len(careplans) == 1

    def test_careplan_fields(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        cp = _get_resources(bundle, "CarePlan")[0]
        assert cp["status"] == "draft"
        assert cp["intent"] == "proposal"
        assert cp["subject"]["reference"].startswith("urn:uuid:")
        assert len(cp["goal"]) == 1
        assert len(cp["activity"]) == 3


class TestPatientResource:
    def test_patient_included_in_bundle(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        patients = _get_resources(bundle, "Patient")
        assert len(patients) == 1

    def test_patient_is_first_entry(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        first = bundle["entry"][0]["resource"]
        assert first["resourceType"] == "Patient"

    def test_patient_conditional_create_with_demographics(self):
        demographics = {
            "id": "patient-1",
            "reference": "Patient/patient-1",
            "name": "John Doe",
            "gender": "male",
            "birth_date": "1970-01-01",
            "identifiers": [
                {"system": "http://hospital.example/mrn", "value": "MRN-12345"},
            ],
        }
        bundle = build_fhir_bundle(_hypertension_brief(), patient_demographics=demographics)
        patient_entry = bundle["entry"][0]
        patient = patient_entry["resource"]
        assert patient["resourceType"] == "Patient"
        assert patient["identifier"][0]["value"] == "MRN-12345"
        assert patient["gender"] == "male"
        assert patient["birthDate"] == "1970-01-01"
        assert patient_entry["request"]["ifNoneExist"] == "identifier=http://hospital.example/mrn|MRN-12345"

    def test_patient_without_demographics(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        patient_entry = bundle["entry"][0]
        assert "ifNoneExist" not in patient_entry["request"]

    def test_all_subject_refs_use_patient_urn(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        patient_urn = bundle["entry"][0]["fullUrl"]
        for entry in bundle["entry"]:
            resource = entry["resource"]
            subject = resource.get("subject", {})
            if subject:
                assert subject["reference"] == patient_urn


class TestGoals:
    def test_goals_created(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        goals = _get_resources(bundle, "Goal")
        assert len(goals) == 1

    def test_goal_has_target(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        goal = _get_resources(bundle, "Goal")[0]
        assert goal["lifecycleStatus"] == "proposed"
        assert "target" in goal
        target = goal["target"][0]
        assert target["measure"]["coding"][0]["code"] == "8480-6"
        assert target["detailRange"]["high"]["value"] == 140


class TestActivities:
    def test_medication_request(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        meds = _get_resources(bundle, "MedicationRequest")
        assert len(meds) == 1
        assert meds[0]["status"] == "draft"
        assert meds[0]["medicationCodeableConcept"]["coding"][0]["code"] == "29046"
        assert "dosageInstruction" in meds[0]

    def test_service_request_monitoring(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        srs = _get_resources(bundle, "ServiceRequest")
        assert len(srs) == 1
        assert srs[0]["code"]["coding"][0]["code"] == "51990-0"

    def test_lifestyle_inline(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        cp = _get_resources(bundle, "CarePlan")[0]
        inline = [a for a in cp["activity"] if "performedActivity" in a]
        assert len(inline) == 1
        assert "DASH" in inline[0]["performedActivity"][0]["text"]


class TestAITransparency:
    def test_aiast_on_all_resources(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        for entry in bundle["entry"]:
            resource = entry["resource"]
            security = resource.get("meta", {}).get("security", [])
            aiast_codes = [s["code"] for s in security if s.get("code") == "AIAST"]
            assert len(aiast_codes) >= 1, f"{resource['resourceType']}/{resource.get('id')} missing AIAST"

    def test_ai_device_present(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        devices = _get_resources(bundle, "Device")
        assert len(devices) == 1
        device = devices[0]
        assert device["type"]["coding"][0]["code"] == "Artificial-Intelligence"
        assert any("AI-Device" in p for p in device["meta"].get("profile", []))

    def test_ai_provenance_present(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        provs = _get_resources(bundle, "Provenance")
        ai_provs = [p for p in provs if any(
            "AI-Provenance" in pr for pr in p.get("meta", {}).get("profile", [])
        )]
        assert len(ai_provs) == 1
        ai_prov = ai_provs[0]
        assert ai_prov["reason"][0]["coding"][0]["code"] == "AIAST"
        assert len(ai_prov["target"]) >= 3

    def test_per_activity_provenance(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        provs = _get_resources(bundle, "Provenance")
        activity_provs = [p for p in provs if "AI-Provenance" not in str(p.get("meta", {}).get("profile", []))]
        assert len(activity_provs) == 3
        for prov in activity_provs:
            entities = prov.get("entity", [])
            assert len(entities) >= 1
            assert entities[0]["role"] == "source"

    def test_inline_activity_provenance_uses_target_path(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        provs = _get_resources(bundle, "Provenance")
        activity_provs = [p for p in provs if "AI-Provenance" not in str(p.get("meta", {}).get("profile", []))]
        inline_provs = [
            p for p in activity_provs
            if any("targetPath" in str(ext.get("url", "")) for t in p.get("target", []) for ext in t.get("extension", []))
        ]
        assert len(inline_provs) == 1
        target = inline_provs[0]["target"][0]
        ext = target["extension"][0]
        assert "targetPath" in ext["url"]
        assert "CarePlan.activity[" in ext["valueString"]
        assert ".performedActivity" in ext["valueString"]

    def test_standalone_activity_provenance_no_target_path(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        provs = _get_resources(bundle, "Provenance")
        activity_provs = [p for p in provs if "AI-Provenance" not in str(p.get("meta", {}).get("profile", []))]
        standalone_provs = [
            p for p in activity_provs
            if not any(t.get("extension") for t in p.get("target", []))
        ]
        assert len(standalone_provs) == 2
        for prov in standalone_provs:
            assert prov["target"][0]["reference"].startswith("urn:uuid:")

    def test_provenance_has_cpg_source(self):
        bundle = build_fhir_bundle(_hypertension_brief())
        provs = _get_resources(bundle, "Provenance")
        ai_provs = [p for p in provs if any(
            "AI-Provenance" in pr for pr in p.get("meta", {}).get("profile", [])
        )]
        ai_prov = ai_provs[0]
        cpg_entities = [e for e in ai_prov["entity"] if e["role"] == "derivation"]
        assert len(cpg_entities) == 1
        assert "SYN-HTN-2026-001" in cpg_entities[0]["what"]["display"]


class TestNodeIntegration:
    def test_fhir_bundle_generator_node(self):
        from acp_writer.nodes.fhir_bundle_generator import fhir_bundle_generator

        brief = _hypertension_brief()
        state = {"planning_brief": brief.model_dump(mode="json")}
        result = fhir_bundle_generator(state)

        assert result["fhir_bundle"]["type"] == "transaction"
        assert len(result["fhir_bundle"]["entry"]) > 0

    def test_empty_brief(self):
        from acp_writer.nodes.fhir_bundle_generator import fhir_bundle_generator

        result = fhir_bundle_generator({"planning_brief": {}})
        assert result["fhir_bundle"]["entry"] == []

    def test_writes_artifact(self, tmp_path):
        from acp_writer.nodes.fhir_bundle_generator import fhir_bundle_generator

        brief = _hypertension_brief()
        state = {
            "planning_brief": brief.model_dump(mode="json"),
            "output_dir": str(tmp_path),
        }
        fhir_bundle_generator(state)
        assert (tmp_path / "fhir-bundle.json").exists()
