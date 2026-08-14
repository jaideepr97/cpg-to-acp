"""Tests for concept-based agent tools (closure-based, no module-level state)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import date

from acp_writer.tools.bundle_inventory import build_bundle_inventory
from acp_writer.tools.qa_agent import _build_tools
from acp_writer.tools.temporal_index import build_temporal_index
from acp_writer.tools.terminology_lookup import LookupResult

PROJECT_ROOT = Path(__file__).parent.parent.parent
BUNDLES_DIR = PROJECT_ROOT / "acp-writer" / "benchmarks" / "bundles"


def _load(name: str) -> dict:
    return json.loads((BUNDLES_DIR / name).read_text())


def _get_tools(bundle_name: str, with_llm: bool = False):
    """Build tools with closure-captured state."""
    bundle = _load(bundle_name)
    inventory = build_bundle_inventory(bundle)
    index = build_temporal_index(bundle)
    ref_date = date(2026, 6, 1)
    llm = MagicMock() if with_llm else None
    tools = _build_tools(bundle, inventory, index, ref_date, llm)
    tool_map = {t.name: t for t in tools}
    return tool_map, llm


class TestCheckConditionTool:
    def test_snomed_condition_by_term(self):
        tools, _ = _get_tools("complex-patient-01.json")
        result = json.loads(tools["check_condition"].invoke({"term": "hypertension"}))
        assert result["found"] is True
        assert result["match_basis"] == "cache"

    @patch("acp_writer.tools.terminology_lookup.find_candidates")
    def test_icd10_condition_via_terminology(self, mock_find):
        mock_find.return_value = [
            LookupResult(found=True, system="http://hl7.org/fhir/sid/icd-10-cm",
                        code="E03.9", display="Hypothyroidism"),
        ]
        tools, _ = _get_tools("messy-data-01.json")
        result = json.loads(tools["check_condition"].invoke({"term": "hypothyroidism"}))
        assert result["found"] is True

    @patch("acp_writer.tools.terminology_lookup.find_candidates", return_value=[])
    def test_display_text_match(self, mock_find):
        tools, _ = _get_tools("messy-data-01.json")
        result = json.loads(tools["check_condition"].invoke({"term": "reflux disease"}))
        assert result["found"] is True
        assert result["match_basis"] == "display_text"

    @patch("acp_writer.tools.terminology_lookup.find_candidates", return_value=[])
    def test_miss_carries_alternatives(self, mock_find):
        tools, _ = _get_tools("messy-data-01.json")
        result = json.loads(tools["check_condition"].invoke({"term": "completely unknown xyz"}))
        assert result["found"] is False
        assert "note" in result


class TestCheckMedicationTool:
    def test_free_text_medication(self):
        tools, _ = _get_tools("messy-data-01.json")
        result = json.loads(tools["check_medication"].invoke({"term": "levothyroxine"}))
        assert result["found"] is True
        assert result["match_basis"] == "display_text"

    def test_coded_medication(self):
        tools, _ = _get_tools("messy-data-01.json")
        result = json.loads(tools["check_medication"].invoke({"term": "metformin"}))
        assert result["found"] is True


class TestLookupObservationTool:
    def test_wrong_loinc_by_display(self):
        tools, _ = _get_tools("messy-data-01.json")
        result = json.loads(tools["lookup_observation"].invoke({"term": "thyroid stimulating hormone"}))
        assert result["found"] is True
        assert result["value"] == 5.8

    @patch("acp_writer.tools.terminology_lookup.find_candidates", return_value=[])
    def test_miss_shows_available_observations(self, mock_find):
        tools, _ = _get_tools("messy-data-01.json")
        result = json.loads(tools["lookup_observation"].invoke({"term": "vitamin D level"}))
        assert result["found"] is False
        assert "note" in result


class TestThyroidDisorderEndToEnd:
    """The findings report's example failure — must now pass."""

    @patch("acp_writer.tools.terminology_lookup.find_candidates")
    def test_thyroid_disorder_resolves(self, mock_find):
        mock_find.return_value = [
            LookupResult(found=True, system="http://hl7.org/fhir/sid/icd-10-cm",
                        code="E03", display="Hypothyroidism"),
        ]
        tools, _ = _get_tools("messy-data-01.json")
        result = json.loads(tools["check_condition"].invoke({"term": "thyroid disorder"}))
        assert result["found"] is True
