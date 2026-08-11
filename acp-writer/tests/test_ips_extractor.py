"""Tests for the IPS Extractor tool."""

import json
from pathlib import Path

from datetime import date

from acp_writer.tools.ips_extractor import (
    extract_allergy,
    extract_condition,
    extract_diagnostic_report,
    extract_family_history,
    extract_medication,
    extract_observation,
    extract_patient_age,
    extract_procedure,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "mock-EHR" / "data"

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"


def _load_bundle(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text())


class TestExtractObservation:
    def test_systolic_bp_from_component(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_observation(bundle, LOINC, "8480-6")
        assert result.found
        assert result.value == 142
        assert result.unit == "mmHg"
        assert result.fhir_reference == "Observation/observation-bp-1"

    def test_diastolic_bp_from_component(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_observation(bundle, LOINC, "8462-4")
        assert result.found
        assert result.value == 92

    def test_lifestyle_patient_bp(self):
        bundle = _load_bundle("patient-bundle-lifestyle.json")
        result = extract_observation(bundle, LOINC, "8480-6")
        assert result.found
        assert result.value == 125

    def test_missing_observation(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_observation(bundle, LOINC, "2345-7")  # glucose
        assert not result.found

    def test_returns_fhir_reference(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_observation(bundle, LOINC, "8480-6")
        assert result.fhir_reference.startswith("Observation/")
        assert result.resource_type == "Observation"

    def test_returns_date(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_observation(bundle, LOINC, "8480-6")
        assert result.date is not None
        assert "2026" in result.date

    def test_empty_bundle(self):
        result = extract_observation({"entry": []}, LOINC, "8480-6")
        assert not result.found

    def test_most_recent_selected(self):
        bundle = {
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": "old",
                        "status": "final",
                        "effectiveDateTime": "2026-01-01",
                        "code": {"coding": [{"system": LOINC, "code": "8480-6"}]},
                        "valueQuantity": {"value": 130, "unit": "mmHg"},
                    },
                },
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": "new",
                        "status": "final",
                        "effectiveDateTime": "2026-07-01",
                        "code": {"coding": [{"system": LOINC, "code": "8480-6"}]},
                        "valueQuantity": {"value": 145, "unit": "mmHg"},
                    },
                },
            ],
        }
        result = extract_observation(bundle, LOINC, "8480-6")
        assert result.value == 145
        assert result.fhir_reference == "Observation/new"


class TestExtractCondition:
    def test_hypertension_present(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_condition(bundle, SNOMED, "59621000")
        assert result.found
        assert result.value is True
        assert result.fhir_reference == "Condition/condition-htn-1"

    def test_diabetes_present(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_condition(bundle, SNOMED, "44054006")
        assert result.found

    def test_diabetes_absent_lifestyle(self):
        bundle = _load_bundle("patient-bundle-lifestyle.json")
        result = extract_condition(bundle, SNOMED, "44054006")
        assert not result.found
        assert result.value is False

    def test_resolved_condition_excluded(self):
        bundle = {
            "entry": [
                {
                    "resource": {
                        "resourceType": "Condition",
                        "id": "c1",
                        "clinicalStatus": {
                            "coding": [{"code": "resolved"}],
                        },
                        "code": {"coding": [{"system": SNOMED, "code": "12345"}]},
                    },
                },
            ],
        }
        result = extract_condition(bundle, SNOMED, "12345")
        assert not result.found

    def test_missing_condition(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_condition(bundle, SNOMED, "9999999")
        assert not result.found


class TestExtractMedication:
    def test_metformin_present(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_medication(bundle, RXNORM, "860975")
        assert result.found
        assert result.fhir_reference == "MedicationStatement/medstmt-metformin-1"

    def test_medication_absent_lifestyle(self):
        bundle = _load_bundle("patient-bundle-lifestyle.json")
        result = extract_medication(bundle, RXNORM, "860975")
        assert not result.found

    def test_cancelled_medication_excluded(self):
        bundle = {
            "entry": [
                {
                    "resource": {
                        "resourceType": "MedicationRequest",
                        "id": "m1",
                        "status": "cancelled",
                        "medicationCodeableConcept": {
                            "coding": [{"system": RXNORM, "code": "12345"}],
                        },
                    },
                },
            ],
        }
        result = extract_medication(bundle, RXNORM, "12345")
        assert not result.found

    def test_medication_request_found(self):
        bundle = {
            "entry": [
                {
                    "resource": {
                        "resourceType": "MedicationRequest",
                        "id": "mr1",
                        "status": "active",
                        "medicationCodeableConcept": {
                            "coding": [{"system": RXNORM, "code": "29046"}],
                        },
                    },
                },
            ],
        }
        result = extract_medication(bundle, RXNORM, "29046")
        assert result.found
        assert result.resource_type == "MedicationRequest"


class TestExtractAllergy:
    def test_allergy_present(self):
        bundle = {
            "entry": [
                {
                    "resource": {
                        "resourceType": "AllergyIntolerance",
                        "id": "a1",
                        "clinicalStatus": {
                            "coding": [{"code": "active"}],
                        },
                        "code": {"coding": [{"system": SNOMED, "code": "91936005"}]},
                    },
                },
            ],
        }
        result = extract_allergy(bundle, SNOMED, "91936005")
        assert result.found
        assert result.fhir_reference == "AllergyIntolerance/a1"

    def test_allergy_absent(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_allergy(bundle, SNOMED, "91936005")
        assert not result.found

    def test_resolved_allergy_excluded(self):
        bundle = {
            "entry": [
                {
                    "resource": {
                        "resourceType": "AllergyIntolerance",
                        "id": "a1",
                        "clinicalStatus": {
                            "coding": [{"code": "resolved"}],
                        },
                        "code": {"coding": [{"system": SNOMED, "code": "91936005"}]},
                    },
                },
            ],
        }
        result = extract_allergy(bundle, SNOMED, "91936005")
        assert not result.found


class TestObservationValueTypes:
    def test_value_codeable_concept(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-smoking",
                    "status": "final",
                    "effectiveDateTime": "2026-04-01",
                    "code": {"coding": [{"system": LOINC, "code": "72166-2"}]},
                    "valueCodeableConcept": {
                        "coding": [{"system": SNOMED, "code": "449868002", "display": "Current every day smoker"}]
                    },
                },
            }],
        }
        result = extract_observation(bundle, LOINC, "72166-2")
        assert result.found
        assert result.value == "449868002"

    def test_value_codeable_concept_text_fallback(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-coded-text",
                    "status": "final",
                    "effectiveDateTime": "2026-04-01",
                    "code": {"coding": [{"system": LOINC, "code": "72166-2"}]},
                    "valueCodeableConcept": {"text": "Never smoker"},
                },
            }],
        }
        result = extract_observation(bundle, LOINC, "72166-2")
        assert result.found
        assert result.value == "Never smoker"

    def test_value_string(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-string",
                    "status": "final",
                    "effectiveDateTime": "2026-03-20",
                    "code": {"coding": [{"system": LOINC, "code": "5811-5"}]},
                    "valueString": "Trace",
                },
            }],
        }
        result = extract_observation(bundle, LOINC, "5811-5")
        assert result.found
        assert result.value == "Trace"

    def test_value_boolean(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-bool",
                    "status": "final",
                    "effectiveDateTime": "2026-04-01",
                    "code": {"coding": [{"system": LOINC, "code": "11111-1"}]},
                    "valueBoolean": True,
                },
            }],
        }
        result = extract_observation(bundle, LOINC, "11111-1")
        assert result.found
        assert result.value is True

    def test_value_quantity_still_works(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-qty",
                    "status": "final",
                    "effectiveDateTime": "2026-05-01",
                    "code": {"coding": [{"system": LOINC, "code": "8480-6"}]},
                    "valueQuantity": {"value": 140, "unit": "mmHg"},
                },
            }],
        }
        result = extract_observation(bundle, LOINC, "8480-6")
        assert result.found
        assert result.value == 140
        assert result.unit == "mmHg"

    def test_no_value_at_all(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-empty",
                    "status": "final",
                    "code": {"coding": [{"system": LOINC, "code": "51990-0"}]},
                },
            }],
        }
        result = extract_observation(bundle, LOINC, "51990-0")
        assert not result.found


class TestExtractProcedure:
    def test_procedure_present(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "Procedure",
                    "id": "proc-1",
                    "status": "completed",
                    "code": {"coding": [{"system": SNOMED, "code": "73761001", "display": "Colonoscopy"}]},
                    "performedDateTime": "2025-06-15",
                },
            }],
        }
        result = extract_procedure(bundle, SNOMED, "73761001")
        assert result.found
        assert result.value is True
        assert result.date == "2025-06-15"

    def test_procedure_absent(self):
        result = extract_procedure({"entry": []}, SNOMED, "73761001")
        assert not result.found

    def test_not_done_excluded(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "Procedure",
                    "id": "proc-1",
                    "status": "not-done",
                    "code": {"coding": [{"system": SNOMED, "code": "73761001"}]},
                },
            }],
        }
        result = extract_procedure(bundle, SNOMED, "73761001")
        assert not result.found


class TestExtractFamilyHistory:
    def test_family_history_present(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "FamilyMemberHistory",
                    "id": "fmh-1",
                    "status": "completed",
                    "relationship": {"coding": [{"system": SNOMED, "code": "72705000", "display": "Mother"}]},
                    "condition": [{
                        "code": {"coding": [{"system": SNOMED, "code": "266894000", "display": "Cardiovascular disease"}]},
                    }],
                },
            }],
        }
        result = extract_family_history(bundle, SNOMED, "266894000")
        assert result.found
        assert result.value is True

    def test_family_history_absent(self):
        result = extract_family_history({"entry": []}, SNOMED, "266894000")
        assert not result.found


class TestExtractPatientAge:
    def test_age_calculation(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "Patient",
                    "id": "p1",
                    "birthDate": "1958-11-30",
                },
            }],
        }
        result = extract_patient_age(bundle, date(2026, 6, 1))
        assert result.found
        assert result.value == 67

    def test_age_before_birthday(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "Patient",
                    "id": "p1",
                    "birthDate": "1971-03-15",
                },
            }],
        }
        result = extract_patient_age(bundle, date(2026, 6, 1))
        assert result.value == 55

    def test_age_on_birthday(self):
        bundle = {
            "entry": [{
                "resource": {
                    "resourceType": "Patient",
                    "id": "p1",
                    "birthDate": "1971-06-01",
                },
            }],
        }
        result = extract_patient_age(bundle, date(2026, 6, 1))
        assert result.value == 55

    def test_no_patient(self):
        result = extract_patient_age({"entry": []}, date(2026, 6, 1))
        assert not result.found

    def test_no_birth_date(self):
        bundle = {
            "entry": [{
                "resource": {"resourceType": "Patient", "id": "p1"},
            }],
        }
        result = extract_patient_age(bundle, date(2026, 6, 1))
        assert not result.found


class TestToDict:
    def test_found_observation(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_observation(bundle, LOINC, "8480-6")
        d = result.to_dict()
        assert d["found"] is True
        assert d["value"] == 142
        assert d["unit"] == "mmHg"
        assert "fhir_reference" in d

    def test_not_found(self):
        bundle = _load_bundle("patient-bundle-medication.json")
        result = extract_observation(bundle, LOINC, "99999-9")
        d = result.to_dict()
        assert d["found"] is False
        assert "value" not in d
