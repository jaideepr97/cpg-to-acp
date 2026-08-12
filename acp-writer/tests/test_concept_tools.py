"""Tests for concept-based agent tools (Task 3)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from acp_writer.tools.bundle_inventory import build_bundle_inventory
from acp_writer.tools.qa_agent import (
    _BUNDLE_HOLDER,
    _INVENTORY_HOLDER,
    _INDEX_HOLDER,
    _LLM_HOLDER,
    _REF_DATE_HOLDER,
    check_condition,
    check_medication,
    lookup_observation,
)
from acp_writer.tools.terminology_lookup import LookupResult
from datetime import date

PROJECT_ROOT = Path(__file__).parent.parent.parent
BUNDLES_DIR = PROJECT_ROOT / "acp-writer" / "benchmarks" / "bundles"


def _load(name: str) -> dict:
    return json.loads((BUNDLES_DIR / name).read_text())


def _setup_context(bundle_name: str, with_llm: bool = False):
    """Set up the tool context holders for testing."""
    bundle = _load(bundle_name)
    inventory = build_bundle_inventory(bundle)
    _BUNDLE_HOLDER["bundle"] = bundle
    _INVENTORY_HOLDER["inventory"] = inventory
    _REF_DATE_HOLDER["date"] = date(2026, 6, 1)

    if with_llm:
        mock_llm = MagicMock()
        _LLM_HOLDER["llm"] = mock_llm
        return mock_llm
    else:
        _LLM_HOLDER.clear()
    return None


def _teardown():
    _BUNDLE_HOLDER.clear()
    _INVENTORY_HOLDER.clear()
    _INDEX_HOLDER.clear()
    _LLM_HOLDER.clear()
    _REF_DATE_HOLDER.clear()


class TestCheckConditionTool:
    def test_snomed_condition_by_term(self):
        _setup_context("complex-patient-01.json")
        try:
            result = json.loads(check_condition.invoke({"term": "hypertension"}))
            assert result["found"] is True
            assert result["match_basis"] == "cache"
        finally:
            _teardown()

    @patch("acp_writer.tools.terminology_lookup.find_candidates")
    def test_icd10_condition_via_terminology(self, mock_find):
        mock_find.return_value = [
            LookupResult(found=True, system="http://hl7.org/fhir/sid/icd-10-cm",
                        code="E03.9", display="Hypothyroidism"),
        ]
        _setup_context("messy-data-01.json")
        try:
            result = json.loads(check_condition.invoke({"term": "hypothyroidism"}))
            assert result["found"] is True
        finally:
            _teardown()

    @patch("acp_writer.tools.terminology_lookup.find_candidates", return_value=[])
    def test_display_text_match(self, mock_find):
        _setup_context("messy-data-01.json")
        try:
            result = json.loads(check_condition.invoke({"term": "reflux disease"}))
            assert result["found"] is True
            assert result["match_basis"] == "display_text"
        finally:
            _teardown()

    @patch("acp_writer.tools.terminology_lookup.find_candidates", return_value=[])
    def test_miss_carries_alternatives(self, mock_find):
        _setup_context("messy-data-01.json")
        try:
            result = json.loads(check_condition.invoke({"term": "completely unknown xyz"}))
            assert result["found"] is False
            assert "note" in result
            assert "conditions" in result["note"].lower() or "Hypertension" in result.get("note", "")
        finally:
            _teardown()


class TestCheckMedicationTool:
    def test_free_text_medication(self):
        _setup_context("messy-data-01.json")
        try:
            result = json.loads(check_medication.invoke({"term": "levothyroxine"}))
            assert result["found"] is True
            assert result["match_basis"] == "display_text"
        finally:
            _teardown()

    def test_coded_medication(self):
        _setup_context("messy-data-01.json")
        try:
            result = json.loads(check_medication.invoke({"term": "metformin"}))
            assert result["found"] is True
        finally:
            _teardown()


class TestLookupObservationTool:
    def test_wrong_loinc_by_display(self):
        _setup_context("messy-data-01.json")
        try:
            result = json.loads(lookup_observation.invoke({"term": "thyroid stimulating hormone"}))
            assert result["found"] is True
            assert result["value"] == 5.8
        finally:
            _teardown()

    @patch("acp_writer.tools.terminology_lookup.find_candidates", return_value=[])
    def test_miss_shows_available_observations(self, mock_find):
        _setup_context("messy-data-01.json")
        try:
            result = json.loads(lookup_observation.invoke({"term": "vitamin D level"}))
            assert result["found"] is False
            assert "note" in result
            assert "observations" in result["note"].lower() or "Available" in result.get("note", "")
        finally:
            _teardown()


class TestThyroidDisorderEndToEnd:
    """The findings report's example failure — must now pass."""

    @patch("acp_writer.tools.terminology_lookup.find_candidates")
    def test_thyroid_disorder_resolves(self, mock_find):
        mock_find.return_value = [
            LookupResult(found=True, system="http://hl7.org/fhir/sid/icd-10-cm",
                        code="E03", display="Hypothyroidism"),
        ]
        _setup_context("messy-data-01.json")
        try:
            result = json.loads(check_condition.invoke({"term": "thyroid disorder"}))
            assert result["found"] is True
        finally:
            _teardown()
