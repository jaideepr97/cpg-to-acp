"""Tests for Recommendation Extractor and Schema Validator."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cpg_ingester.nodes.rec_extractor import rec_extractor
from cpg_ingester.nodes.rec_schema_validator import rec_schema_validator
from cpg_ingester.validators.rec_schema import validate_recommendation, validate_recommendations


VALID_REC = {
    "id": "aaa-bbb-ccc-ddd",
    "source_cpg": "CPG-001",
    "section": "3.4",
    "title": "DASH Diet",
    "content": "Adopt the DASH diet emphasizing fruits and vegetables.",
    "recommendation_type": "lifestyle",
    "certainty": {
        "strength": "strong-for",
        "evidence_quality": "high",
        "grading_system": None,
        "original_grade": "Strong recommendation, high-certainty evidence",
    },
    "scope_notes": None,
    "remarks": None,
    "rationale": None,
    "cross_references": [],
    "provenance": "reviewed",
    "evidence_review_date": None,
    "source_location": {
        "page_start": 5,
        "page_end": None,
        "source_text": "Adopt the DASH diet...",
    },
}


class TestRecSchemaValidator:

    def test_valid_recommendation(self):
        errors = validate_recommendation(VALID_REC, manifest_ids={"aaa-bbb-ccc-ddd"})
        assert errors == [], f"Unexpected errors: {errors}"

    def test_invalid_rec_type(self):
        rec = {**VALID_REC, "recommendation_type": "bogus"}
        errors = validate_recommendation(rec, manifest_ids={"aaa-bbb-ccc-ddd"})
        assert any("recommendation_type" in e for e in errors)

    def test_invalid_strength(self):
        rec = {**VALID_REC, "certainty": {"strength": "very-strong", "evidence_quality": "high"}}
        errors = validate_recommendation(rec, manifest_ids={"aaa-bbb-ccc-ddd"})
        assert any("strength" in e for e in errors)

    def test_invalid_evidence(self):
        rec = {**VALID_REC, "certainty": {"strength": "strong-for", "evidence_quality": "excellent"}}
        errors = validate_recommendation(rec, manifest_ids={"aaa-bbb-ccc-ddd"})
        assert any("evidence_quality" in e for e in errors)

    def test_invalid_provenance(self):
        rec = {**VALID_REC, "provenance": "original"}
        errors = validate_recommendation(rec, manifest_ids={"aaa-bbb-ccc-ddd"})
        assert any("provenance" in e for e in errors)

    def test_cross_ref_not_in_manifest(self):
        rec = {**VALID_REC, "cross_references": [{"target_id": "nonexistent-id", "relationship": "related"}]}
        errors = validate_recommendation(rec, manifest_ids={"aaa-bbb-ccc-ddd"})
        assert any("cross_reference" in e for e in errors)

    def test_id_not_in_manifest(self):
        errors = validate_recommendation(VALID_REC, manifest_ids={"other-id"})
        assert any("not in manifest" in e for e in errors)

    def test_grading_system_mismatch(self):
        rec = {**VALID_REC, "certainty": {
            "strength": "strong-for", "evidence_quality": "high",
            "grading_system": "COR-LOE",
        }}
        errors = validate_recommendation(rec, manifest_ids={"aaa-bbb-ccc-ddd"}, declared_grading="GRADE")
        assert any("doesn't match" in e for e in errors)

    def test_page_exceeds_document(self):
        rec = {**VALID_REC, "source_location": {"page_start": 100, "page_end": None}}
        errors = validate_recommendation(rec, manifest_ids={"aaa-bbb-ccc-ddd"}, max_page=10)
        assert any("exceeds" in e for e in errors)

    def test_no_certainty_is_valid(self):
        rec = {**VALID_REC, "certainty": None}
        errors = validate_recommendation(rec, manifest_ids={"aaa-bbb-ccc-ddd"})
        assert errors == []

    def test_batch_validation(self):
        recs = [VALID_REC, {**VALID_REC, "id": "xxx-yyy", "recommendation_type": "bogus"}]
        errors = validate_recommendations(recs, manifest_ids={"aaa-bbb-ccc-ddd", "xxx-yyy"})
        assert len(errors) == 1
        assert "recommendation_type" in errors[0]


class TestRecSchemaValidatorNode:

    def test_passes_valid_recs(self):
        state = {
            "recommendations": [VALID_REC],
            "items": [{"id": "aaa-bbb-ccc-ddd"}],
        }
        result = rec_schema_validator(state)
        assert result["schema_errors"] == []

    def test_fails_empty_recs(self):
        state = {"recommendations": [], "items": []}
        result = rec_schema_validator(state)
        assert len(result["schema_errors"]) > 0

    def test_reports_validation_errors(self):
        bad_rec = {**VALID_REC, "recommendation_type": "bogus"}
        state = {
            "recommendations": [bad_rec],
            "items": [{"id": "aaa-bbb-ccc-ddd"}],
        }
        result = rec_schema_validator(state)
        assert len(result["schema_errors"]) > 0


MOCK_LLM_RESPONSE = json.dumps({
    "recommendations": [
        {
            "id": "rec-guid-1",
            "source_cpg": "TBD",
            "section": "3.4",
            "title": "DASH Diet",
            "content": "Adopt the DASH diet.",
            "recommendation_type": "lifestyle",
            "certainty": {"strength": "strong-for", "evidence_quality": "high", "grading_system": None, "original_grade": None},
            "scope_notes": None,
            "remarks": None,
            "rationale": None,
            "cross_references": [],
            "provenance": "reviewed",
            "evidence_review_date": None,
            "source_location": {"page_start": 5, "page_end": None, "source_text": "Adopt the DASH diet..."},
        },
    ],
})


class TestRecExtractorNode:

    def test_extracts_recommendations(self):
        mock_llm = MagicMock()
        mock_llm.invoke = MagicMock(return_value=MagicMock(content=MOCK_LLM_RESPONSE))

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "items": [{"id": "rec-guid-1", "title": "DASH Diet", "section": "3.4"}],
                "source_pages": "Adopt the DASH diet...",
                "grading_definitions": "GRADE",
                "abbreviations": {"DASH": "Dietary Approaches to Stop Hypertension"},
                "output_dir": tmpdir,
            }
            with patch("cpg_ingester.nodes.rec_extractor.get_llm", return_value=mock_llm):
                result = rec_extractor(state)

            assert len(result["recommendations"]) == 1
            assert result["recommendations"][0]["title"] == "DASH Diet"
            assert result["schema_errors"] == []

    def test_writes_artifact(self):
        mock_llm = MagicMock()
        mock_llm.invoke = MagicMock(return_value=MagicMock(content=MOCK_LLM_RESPONSE))

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "items": [{"id": "rec-guid-1", "section": "3.4"}],
                "source_pages": "content",
                "grading_definitions": "",
                "abbreviations": {},
                "output_dir": tmpdir,
            }
            with patch("cpg_ingester.nodes.rec_extractor.get_llm", return_value=mock_llm):
                rec_extractor(state)

            rec_files = list(Path(tmpdir).glob("recommendations-*.json"))
            assert len(rec_files) == 1

    def test_includes_feedback_on_retry(self):
        mock_llm = MagicMock()
        mock_llm.invoke = MagicMock(return_value=MagicMock(content=MOCK_LLM_RESPONSE))

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "items": [{"id": "rec-guid-1", "section": "3.4"}],
                "source_pages": "content",
                "grading_definitions": "",
                "abbreviations": {},
                "output_dir": tmpdir,
                "schema_errors": ["Missing title field"],
                "review_count": 0,
            }
            with patch("cpg_ingester.nodes.rec_extractor.get_llm", return_value=mock_llm):
                result = rec_extractor(state)

            assert result["review_count"] == 1
            call_args = mock_llm.invoke.call_args[0][0]
            user_msg = call_args[1]["content"]
            assert "SCHEMA ERRORS" in user_msg

    def test_handles_parse_failure(self):
        mock_llm = MagicMock()
        mock_llm.invoke = MagicMock(return_value=MagicMock(content="not json"))

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "items": [{"id": "rec-guid-1", "section": "3.4"}],
                "source_pages": "content",
                "grading_definitions": "",
                "abbreviations": {},
                "output_dir": tmpdir,
            }
            with patch("cpg_ingester.nodes.rec_extractor.get_llm", return_value=mock_llm):
                result = rec_extractor(state)

            assert result["recommendations"] == []
            assert len(result["schema_errors"]) > 0

    def test_empty_items_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"items": [], "output_dir": tmpdir}
            result = rec_extractor(state)
            assert result["recommendations"] == []
