"""Tests for the Docling Agent node."""

import tempfile
from pathlib import Path

import pytest

from cpg_contracts import SourceLocation
from cpg_ingester.nodes.docling_agent import (
    _build_heading_page_map,
    _extract_source_location,
    _ocr_enabled,
    docling_agent,
)

SYNTHETIC_CPG = Path(__file__).parent.parent / "data" / "synthetic-hypertension-cpg.pdf"
_SYNTH_DIR = Path(__file__).parent / "benchmarks" / "parsing" / "synthetic"
FLOWCHART_CPG = _SYNTH_DIR / "flowchart-heavy.pdf"
SCANNED_CPG = _SYNTH_DIR / "single-column-scanned.pdf"
MULTI_FIGURE_CPG = _SYNTH_DIR / "multi-figure.pdf"


def _rapidocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except Exception:
        return False


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


@pytest.mark.skipif(not MULTI_FIGURE_CPG.exists(), reason="Multi-figure PDF not found")
class TestMultiFigurePlacement:
    """Two distinct figures must be extracted in reading order and each anchored
    to its own document position — the invariant P5 relies on to place an
    interpretation next to the right figure (not the anonymous <!-- image -->)."""

    def test_extracts_two_figures_in_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(MULTI_FIGURE_CPG), "output_dir": tmpdir}
            result = docling_agent(state)
            figs = result["figures"]
            assert len(figs) == 2
            assert [f["id"] for f in figs] == ["fig-001", "fig-002"]
            assert all("flow" in (f["classification"] or "").lower() for f in figs)
            # fig-001 is on page 1 (Algorithm A), fig-002 on page 2 (Algorithm B).
            assert figs[0]["page"] == 1
            assert figs[1]["page"] == 2

    def test_pictures_anchored_between_correct_headings(self):
        # The stable anchor is body reading order: picture 0 falls after the
        # "Algorithm A" heading and before "Algorithm B"; picture 1 after "B".
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(MULTI_FIGURE_CPG), "output_dir": tmpdir}
            dj = docling_agent(state)["docling_json"]

        order = [c["$ref"] for c in dj["body"]["children"]]
        text_by_ref = {t["self_ref"]: (t.get("text") or "") for t in dj["texts"]}

        def heading_pos(substr):
            for i, ref in enumerate(order):
                if substr in text_by_ref.get(ref, ""):
                    return i
            raise AssertionError(f"heading {substr!r} not in reading order")

        pic0 = order.index("#/pictures/0")
        pic1 = order.index("#/pictures/1")
        a = heading_pos("Algorithm A")
        b = heading_pos("Algorithm B")
        notes = heading_pos("Combined Notes")

        assert a < pic0 < b, "figure A must sit under heading A, before heading B"
        assert b < pic1 < notes, "figure B must sit under heading B, before Notes"


class TestOcrEnabledFlag:
    """The INGESTION_OCR_ENABLED gate for the conditional-OCR re-parse (P4)."""

    def test_default_on(self, monkeypatch):
        monkeypatch.delenv("INGESTION_OCR_ENABLED", raising=False)
        assert _ocr_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "FALSE", "no", "off", " Off "])
    def test_falsey_values_disable(self, monkeypatch, val):
        monkeypatch.setenv("INGESTION_OCR_ENABLED", val)
        assert _ocr_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on", "anything"])
    def test_other_values_enable(self, monkeypatch, val):
        monkeypatch.setenv("INGESTION_OCR_ENABLED", val)
        assert _ocr_enabled() is True


@pytest.mark.skipif(not SCANNED_CPG.exists(), reason="Scanned benchmark PDF not found")
@pytest.mark.skipif(not _rapidocr_available(), reason="RapidOCR not installed")
class TestConditionalOcr:
    """P4: a scanned PDF triggers an OCR re-parse that recovers text."""

    def test_ocr_recovers_scanned_text(self):
        # Without OCR this fixture yields ~0 chars/page (no text layer); the
        # conditional re-parse should recover a substantial amount of text.
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(SCANNED_CPG), "output_dir": tmpdir}
            result = docling_agent(state)
            assert len(result["markdown"]) > 500

    def test_ocr_disabled_leaves_text_unrecovered(self, monkeypatch):
        monkeypatch.setenv("INGESTION_OCR_ENABLED", "0")
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {"pdf_path": str(SCANNED_CPG), "output_dir": tmpdir}
            result = docling_agent(state)
            # OCR gated off → no text layer to extract.
            assert len(result["markdown"]) < 100


class TestSourceLocationHelper:

    def test_source_location_from_docling(self):
        loc = SourceLocation(page_start=3, page_end=None, bbox=[58, 683, 494, 677], source_text="test")
        assert loc.page_start == 3
        assert loc.bbox == [58, 683, 494, 677]

    def test_source_location_minimal(self):
        loc = SourceLocation(page_start=1)
        assert loc.page_end is None
        assert loc.bbox is None
