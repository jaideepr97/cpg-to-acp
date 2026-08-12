"""Tests for deterministic answer verification guardrails (Task 4)."""

import json
from pathlib import Path

from acp_writer.tools.answer_guardrails import (
    check_concept_consistency,
    check_conflict_enforcement,
    check_provenance_required,
    check_value_consistency,
    verify_answer,
)
from acp_writer.tools.bundle_inventory import build_bundle_inventory

PROJECT_ROOT = Path(__file__).parent.parent.parent
BUNDLES_DIR = PROJECT_ROOT / "acp-writer" / "benchmarks" / "bundles"


def _load(name: str) -> dict:
    return json.loads((BUNDLES_DIR / name).read_text())


class TestProvenanceRequired:
    def test_answer_without_provenance_downgraded(self):
        answer = {"answer": 142, "provenance": [], "insufficient_data": False}
        result = check_provenance_required(answer)
        assert result["insufficient_data"] is True
        assert result["guardrail"] == "provenance_required"

    def test_answer_with_provenance_passes(self):
        answer = {"answer": 142, "provenance": ["Observation/o1"], "insufficient_data": False}
        result = check_provenance_required(answer)
        assert result["answer"] == 142
        assert "guardrail" not in result

    def test_insufficient_data_passes_through(self):
        answer = {"answer": None, "provenance": [], "insufficient_data": True}
        result = check_provenance_required(answer)
        assert result["insufficient_data"] is True
        assert "guardrail" not in result


class TestValueConsistency:
    def test_matching_value_passes(self):
        bundle = {"entry": [{"resource": {
            "resourceType": "Observation", "id": "o1",
            "valueQuantity": {"value": 142, "unit": "mmHg"},
        }}]}
        answer = {"answer": 142, "provenance": ["Observation/o1"], "insufficient_data": False}
        result = check_value_consistency(answer, bundle)
        assert result["answer"] == 142

    def test_non_numeric_passes(self):
        answer = {"answer": True, "provenance": ["Condition/c1"], "insufficient_data": False}
        result = check_value_consistency(answer, {})
        assert result["answer"] is True


class TestConceptConsistency:
    def test_wrong_observation_cited_downgraded(self):
        """Citing potassium when asked about creatinine should be caught."""
        bundle = _load("complex-patient-01.json")
        inventory = build_bundle_inventory(bundle)

        answer = {
            "answer": 4.2,
            "provenance": ["Observation/obs-k-01"],
            "insufficient_data": False,
        }
        result = check_concept_consistency(answer, "creatinine", inventory)
        assert result["insufficient_data"] is True
        assert result.get("guardrail") == "concept_consistency"

    def test_correct_citation_passes(self):
        bundle = _load("complex-patient-01.json")
        inventory = build_bundle_inventory(bundle)

        answer = {
            "answer": 7.8,
            "provenance": ["Observation/obs-hba1c-01"],
            "insufficient_data": False,
        }
        result = check_concept_consistency(answer, "HbA1c", inventory)
        assert result["answer"] == 7.8
        assert "guardrail" not in result


class TestConflictEnforcement:
    def test_conflicting_potassium_downgraded(self):
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)

        answer = {
            "answer": 4.8,
            "provenance": ["Observation/obs-k-m1b"],
            "insufficient_data": False,
        }
        result = check_conflict_enforcement(answer, bundle, inventory)
        assert result["insufficient_data"] is True
        assert result.get("guardrail") == "conflict_enforcement"

    def test_non_conflicting_passes(self):
        bundle = _load("complex-patient-01.json")
        inventory = build_bundle_inventory(bundle)

        answer = {
            "answer": 4.2,
            "provenance": ["Observation/obs-k-01"],
            "insufficient_data": False,
        }
        result = check_conflict_enforcement(answer, bundle, inventory)
        assert result["answer"] == 4.2
        assert "guardrail" not in result


class TestLayeringFallThrough:
    def test_resolver_negative_falls_through(self):
        """A resolver-layer negative boolean should not short-circuit."""
        from datetime import date
        from unittest.mock import MagicMock, patch

        from acp_writer.benchmark.backends.llm_assisted import LLMAssistedBackend
        from acp_writer.benchmark.models import QAAnswer

        backend = LLMAssistedBackend()
        backend._llm = MagicMock()

        bundle = _load("messy-data-01.json")

        with patch.object(backend, "_llm_resolve") as mock_resolve:
            mock_resolve.return_value = QAAnswer(value=True, kind="boolean", answered_by="agent")

            result = backend.answer(
                "Does the patient have a thyroid disorder?",
                bundle,
                date(2026, 6, 1),
            )

            # "thyroid disorder" is not in the concept resolver map
            # so it should fall through to _llm_resolve
            mock_resolve.assert_called_once()
