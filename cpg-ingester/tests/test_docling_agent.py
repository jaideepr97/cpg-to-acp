"""Tests for the Docling Agent node."""

import tempfile
from pathlib import Path

import pytest

from cpg_contracts import SourceLocation
from cpg_ingester.nodes.docling_agent import (
    _build_heading_page_map,
    _extract_source_location,
    docling_agent,
)

SYNTHETIC_CPG = Path(__file__).parent.parent / "data" / "synthetic-hypertension-cpg.pdf"
FLOWCHART_CPG = (
    Path(__file__).parent / "benchmarks" / "parsing" / "synthetic" / "flowchart-heavy.pdf"
)


@pytest.mark.skipif(not SYNTHETIC_CPG.exists(), reason="Synthetic CPG PDF not found")
class TestDoclingAgent:

    def test_produces_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(SYNTHETIC_CPG), "output_dir": tmpdir}
            result = docling_agent(state)
            assert "markdown" in result
            assert len(result["markdown"]) > 1000

    def test_produces_docling_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(SYNTHETIC_CPG), "output_dir": tmpdir}
            result = docling_agent(state)
            assert "docling_json" in result
            assert "texts" in result["docling_json"]

    def test_docling_json_has_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(SYNTHETIC_CPG), "output_dir": tmpdir}
            result = docling_agent(state)
            texts = result["docling_json"].get("texts", [])
            with_prov = [t for t in texts if t.get("prov")]
            assert len(with_prov) > 0
            first_prov = with_prov[0]["prov"][0]
            assert "page_no" in first_prov
            assert "bbox" in first_prov

    def test_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(SYNTHETIC_CPG), "output_dir": tmpdir}
            docling_agent(state)
            assert (Path(tmpdir) / "parsed.md").exists()
            assert (Path(tmpdir) / "heading-page-map.json").exists()

    def test_markdown_contains_expected_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(SYNTHETIC_CPG), "output_dir": tmpdir}
            result = docling_agent(state)
            md = result["markdown"]
            assert "Hypertension" in md
            assert "Lisinopril" in md
            assert "DASH" in md

    def test_returns_figure_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(SYNTHETIC_CPG), "output_dir": tmpdir}
            result = docling_agent(state)
            assert isinstance(result.get("figures"), list)
            assert isinstance(result.get("figure_images"), dict)

    def test_docling_json_has_no_embedded_bitmaps(self):
        # Picture images are stripped before serialization to keep docling_json
        # lean; bitmaps live in the figures index / figure_images instead.
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(SYNTHETIC_CPG), "output_dir": tmpdir}
            result = docling_agent(state)
            for pic in result["docling_json"].get("pictures", []):
                assert pic.get("image") is None


@pytest.mark.skipif(not FLOWCHART_CPG.exists(), reason="Flowchart benchmark PDF not found")
class TestFigureExtraction:

    def test_extracts_classified_flowchart_figure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(FLOWCHART_CPG), "output_dir": tmpdir}
            result = docling_agent(state)

            figures = result["figures"]
            assert len(figures) >= 1

            fig = figures[0]
            assert fig["id"] == "fig-001"
            assert fig["page"] == 1
            assert fig["bbox"] is not None
            # The fixture embeds a flowchart raster; the classifier should tag it.
            assert fig["classification"] is not None
            assert "flow" in fig["classification"].lower()

            # Bitmap captured: local artifact + base64 in figure_images.
            assert fig["image_filename"] == "figures/fig-001.png"
            assert (Path(tmpdir) / "figures" / "fig-001.png").exists()
            assert (Path(tmpdir) / "figures-index.json").exists()
            assert fig["id"] in result["figure_images"]

    def test_figure_bitmap_is_valid_png(self):
        import base64

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(FLOWCHART_CPG), "output_dir": tmpdir}
            result = docling_agent(state)
            b64 = result["figure_images"]["fig-001"]
            png = base64.b64decode(b64)
            assert png[:8] == b"\x89PNG\r\n\x1a\n"


class TestSourceLocationHelper:

    def test_source_location_from_docling(self):
        loc = SourceLocation(page_start=3, page_end=None, bbox=[58, 683, 494, 677], source_text="test")
        assert loc.page_start == 3
        assert loc.bbox == [58, 683, 494, 677]

    def test_source_location_minimal(self):
        loc = SourceLocation(page_start=1)
        assert loc.page_end is None
        assert loc.bbox is None
