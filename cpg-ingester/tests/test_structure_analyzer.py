"""Tests for the Structure Analyzer node."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cpg_ingester.nodes.structure_analyzer import (
    _build_section_page_ranges,
    _extract_abbreviations,
    _extract_sections_from_docling,
    _parse_llm_json,
    structure_analyzer,
)


class TestExtractSections:

    def test_extracts_section_headers(self):
        docling_json = {
            "texts": [
                {"label": "section_header", "text": "1. Introduction", "prov": [{"page_no": 1, "bbox": {"l": 0, "t": 0, "r": 100, "b": 20}}]},
                {"label": "text", "text": "Some body text", "prov": [{"page_no": 1, "bbox": {"l": 0, "t": 30, "r": 100, "b": 50}}]},
                {"label": "section_header", "text": "2. Methods", "prov": [{"page_no": 2, "bbox": {"l": 0, "t": 0, "r": 100, "b": 20}}]},
            ]
        }
        sections = _extract_sections_from_docling(docling_json)
        assert len(sections) == 2
        assert sections[0]["heading"] == "1. Introduction"
        assert sections[0]["page_no"] == 1
        assert sections[1]["heading"] == "2. Methods"
        assert sections[1]["page_no"] == 2

    def test_includes_title_items(self):
        docling_json = {
            "texts": [
                {"label": "title", "text": "Guideline Title", "prov": [{"page_no": 1, "bbox": {"l": 0, "t": 0, "r": 100, "b": 20}}]},
            ]
        }
        sections = _extract_sections_from_docling(docling_json)
        assert len(sections) == 1
        assert sections[0]["heading"] == "Guideline Title"

    def test_handles_missing_prov(self):
        docling_json = {
            "texts": [
                {"label": "section_header", "text": "No Prov", "prov": []},
            ]
        }
        sections = _extract_sections_from_docling(docling_json)
        assert len(sections) == 1
        assert sections[0]["page_no"] is None


class TestBuildPageRanges:

    def test_assigns_page_end(self):
        sections = [
            {"heading": "A", "page_no": 1},
            {"heading": "B", "page_no": 3},
            {"heading": "C", "page_no": 5},
        ]
        result = _build_section_page_ranges(sections, total_pages=7)
        assert result[0]["page_end"] == 3
        assert result[1]["page_end"] == 5
        assert result[2]["page_end"] == 7


class TestExtractAbbreviations:

    def test_extracts_dash_pattern(self):
        text = "BP - Blood Pressure\nCKD - Chronic Kidney Disease\n"
        abbrs = _extract_abbreviations(text)
        assert "BP" in abbrs
        assert "CKD" in abbrs

    def test_extracts_parenthetical_pattern(self):
        text = "Dietary Approaches to Stop Hypertension (DASH) diet"
        abbrs = _extract_abbreviations(text)
        assert "DASH" in abbrs

    def test_skips_short_definitions(self):
        text = "XX - ab\n"
        abbrs = _extract_abbreviations(text)
        assert "XX" not in abbrs


class TestParseLLMJson:

    def test_parses_plain_json(self):
        result = _parse_llm_json('[{"key": "value"}]')
        assert result == [{"key": "value"}]

    def test_strips_markdown_fences(self):
        result = _parse_llm_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_raises_on_invalid(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_llm_json("not json at all")


SYNTHETIC_CPG = Path(__file__).parent.parent / "data" / "synthetic-hypertension-cpg.pdf"


@pytest.mark.skipif(not SYNTHETIC_CPG.exists(), reason="Synthetic CPG not found")
class TestStructureAnalyzerWithMockedLLM:

    def _make_state_with_docling(self, tmpdir):
        from cpg_ingester.nodes.docling_agent import docling_agent
        state = {"pdf_path": str(SYNTHETIC_CPG), "output_dir": tmpdir}
        return docling_agent(state) | {"output_dir": tmpdir}

    def test_extracts_sections_from_real_docling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state_with_docling(tmpdir)
            sections = _extract_sections_from_docling(state["docling_json"])
            assert len(sections) >= 10
            headings = [s["heading"] for s in sections]
            assert any("Recommendation" in h for h in headings)

    def test_with_mocked_llm(self):
        mock_classifications = json.dumps([
            {"heading": "1. Scope and Purpose", "classification": "skip", "reason": "background"},
            {"heading": "3. Recommendations", "classification": "both", "reason": "contains decisions and recs"},
        ])
        mock_archetype = json.dumps({"archetype": "institutional", "confidence": "high", "reason": "standalone format"})
        mock_grading = json.dumps({"grading_system": "GRADE", "definitions": "Strong/Conditional x High/Moderate/Low/Very Low"})

        mock_llm = MagicMock()
        mock_llm.invoke = MagicMock(side_effect=[
            MagicMock(content=mock_classifications),
            MagicMock(content=mock_archetype),
            MagicMock(content=mock_grading),
        ])

        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state_with_docling(tmpdir)

            with patch("cpg_ingester.nodes.structure_analyzer.get_llm", return_value=mock_llm):
                result = structure_analyzer(state)

            assert "section_map" in result
            assert len(result["section_map"]) > 0
            assert result["archetype"] == "institutional"
            assert "abbreviations" in result
            assert isinstance(result["abbreviations"], dict)
            assert (Path(tmpdir) / "section-map.json").exists()
            assert (Path(tmpdir) / "abbreviations.json").exists()

    def test_abbreviation_extraction_on_real_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state_with_docling(tmpdir)
            abbrs = _extract_abbreviations(state["markdown"])
            assert len(abbrs) > 0
            assert any(k in abbrs for k in ["DASH", "CKD", "ACE", "BP", "SBP", "BMP"])
