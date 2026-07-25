"""Tests for the Plan Composer node."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from acp_writer.nodes.plan_composer import (
    _format_conditions,
    _format_demographics,
    _format_recommendations,
    _parse_brief_from_response,
    plan_composer,
)
from acp_writer.planning_brief import PlanningBrief

SAMPLE_BRIEF_JSON = json.dumps({
    "patient_reference": "Patient/patient-1",
    "applicable_cpgs": ["SYN-HTN-2026-001"],
    "dmn_audit_trail": [],
    "goals": [
        {
            "description": "Lower blood pressure to target range",
            "target_measure_code": {"system": "http://loinc.org", "code": "8480-6", "display": "Systolic BP"},
            "target_value": {"high": 140, "unit": "mmHg"},
            "source_recommendation_id": "rec-123",
            "source_cpg": "SYN-HTN-2026-001",
        }
    ],
    "activities": [
        {
            "type": "medication",
            "description": "Start Lisinopril 10mg daily",
            "code": {"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "29046", "display": "Lisinopril"},
            "dose": "10 mg",
            "route": "oral",
            "frequency": "daily",
            "source_recommendation_id": "rec-456",
            "source_cpg": "SYN-HTN-2026-001",
            "source_dmn_call": 0,
            "clinical_rationale": "ACE inhibitor for hypertension with diabetes",
            "workflow": {
                "actor": "prescribing_physician",
                "escalation": "If BP not at target after 4 weeks, increase dose",
                "monitoring_trigger": "BMP in 4 weeks",
            },
        },
        {
            "type": "lifestyle",
            "description": "DASH diet",
            "source_recommendation_id": "rec-789",
            "source_cpg": "SYN-HTN-2026-001",
        },
    ],
    "conflicts": [],
    "review_status": "pending",
})


class TestFormatHelpers:
    def test_format_conditions(self):
        codes = [
            {"system": "http://snomed.info/sct", "code": "59621000", "display": "Essential hypertension"},
            {"system": "http://snomed.info/sct", "code": "44054006", "display": "Type 2 diabetes"},
        ]
        result = _format_conditions(codes)
        assert "Essential hypertension" in result
        assert "Type 2 diabetes" in result

    def test_format_conditions_empty(self):
        assert "No conditions" in _format_conditions([])

    def test_format_demographics(self):
        demo = {"name": "James Reynolds", "gender": "male", "birth_date": "1971-03-15"}
        result = _format_demographics(demo)
        assert "James Reynolds" in result
        assert "male" in result

    def test_format_demographics_empty(self):
        assert _format_demographics({}) == "Unknown"

    def test_format_recommendations(self):
        recs = [{"id": "r1", "title": "Start ACE inhibitor", "content": "...", "recommendation_type": "treatment", "source_cpg": "X"}]
        result = _format_recommendations(recs)
        assert "Start ACE inhibitor" in result

    def test_format_recommendations_empty(self):
        assert "No recommendations" in _format_recommendations([])


class TestParseBrief:
    def test_plain_json(self):
        data = _parse_brief_from_response(SAMPLE_BRIEF_JSON)
        assert data["patient_reference"] == "Patient/patient-1"

    def test_markdown_code_block(self):
        wrapped = f"```json\n{SAMPLE_BRIEF_JSON}\n```"
        data = _parse_brief_from_response(wrapped)
        assert data["patient_reference"] == "Patient/patient-1"

    def test_validates_as_planning_brief(self):
        data = _parse_brief_from_response(SAMPLE_BRIEF_JSON)
        brief = PlanningBrief.model_validate(data)
        assert len(brief.goals) == 1
        assert len(brief.activities) == 2


class TestPlanComposer:
    def _make_state(self) -> dict:
        return {
            "patient_reference": "Patient/patient-1",
            "patient_demographics": {"name": "James Reynolds", "gender": "male", "birth_date": "1971-03-15"},
            "condition_codes": [{"system": "http://snomed.info/sct", "code": "59621000", "display": "Essential hypertension"}],
            "dmn_results": [{
                "model_id": "treatment-recommendation",
                "model_name": "Treatment Recommendation",
                "inputs": {"Systolic BP": 142},
                "outputs": {"Treatment Recommendation": {"Action": "Start medication", "Medication": "Lisinopril"}},
                "fhir_references": ["Observation/bp-1"],
                "timestamp": "2026-07-21T10:00:00Z",
            }],
            "recommendations": [
                {"id": "rec-123", "title": "BP Target", "content": "Target < 140 mmHg", "recommendation_type": "treatment", "source_cpg": "SYN-HTN-2026-001"},
                {"id": "rec-456", "title": "First-line medication", "content": "Lisinopril 10mg", "recommendation_type": "treatment", "source_cpg": "SYN-HTN-2026-001"},
                {"id": "rec-789", "title": "DASH diet", "content": "Adopt DASH diet", "recommendation_type": "lifestyle", "source_cpg": "SYN-HTN-2026-001"},
            ],
            "applicable_cpgs": [{"cpg_id": "SYN-HTN-2026-001"}],
            "litellm_url": "http://localhost:4000",
            "llm_model": "default",
            "llm_api_key": "sk-test",
        }

    @patch("acp_writer.nodes.plan_composer.get_llm")
    def test_produces_valid_brief(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = SAMPLE_BRIEF_JSON
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = plan_composer(self._make_state())

        assert "planning_brief" in result
        brief = PlanningBrief.model_validate(result["planning_brief"])
        assert len(brief.goals) >= 1
        assert len(brief.activities) >= 1
        assert brief.activities[0].source_cpg == "SYN-HTN-2026-001"

    @patch("acp_writer.nodes.plan_composer.get_llm")
    def test_clears_review_feedback(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = SAMPLE_BRIEF_JSON
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = plan_composer(self._make_state())
        assert result["brief_review_feedback"] == ""

    @patch("acp_writer.nodes.plan_composer.get_llm")
    def test_handles_parse_error(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "I cannot create a care plan because..."
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = plan_composer(self._make_state())
        assert result["planning_brief"]["review_status"] == "flagged"
        assert "parse error" in result["planning_brief"]["review_feedback"].lower()

    @patch("acp_writer.nodes.plan_composer.get_llm")
    def test_includes_feedback_in_prompt(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = SAMPLE_BRIEF_JSON
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        state = self._make_state()
        state["brief_review_feedback"] = "Missing monitoring activity for BMP"
        plan_composer(state)

        call_args = mock_llm.invoke.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "Missing monitoring activity" in user_msg

    @patch("acp_writer.nodes.plan_composer.get_llm")
    def test_writes_artifact(self, mock_get_llm, tmp_path):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = SAMPLE_BRIEF_JSON
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        state = self._make_state()
        state["output_dir"] = str(tmp_path)
        plan_composer(state)

        artifact = tmp_path / "planning-brief.json"
        assert artifact.exists()
        data = json.loads(artifact.read_text())
        assert data["patient_reference"] == "Patient/patient-1"
