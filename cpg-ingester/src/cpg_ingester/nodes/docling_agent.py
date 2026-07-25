"""Docling Agent — converts CPG PDF to markdown + JSON with provenance data."""

import logging
from pathlib import Path

import mlflow
from docling.document_converter import DocumentConverter
from docling_core.types.doc import DocItem, SectionHeaderItem, TextItem

from cpg_contracts import SourceLocation
from cpg_ingester.output import write_artifact

logger = logging.getLogger(__name__)


def _extract_source_location(item: DocItem) -> SourceLocation | None:
    """Map a Docling DocItem's provenance to a SourceLocation."""
    if not item.prov:
        return None

    first = item.prov[0]
    last = item.prov[-1] if len(item.prov) > 1 else first

    bbox = [first.bbox.l, first.bbox.t, first.bbox.r, first.bbox.b]

    text = None
    if isinstance(item, TextItem) and item.text:
        text = item.text[:200]

    return SourceLocation(
        page_start=first.page_no,
        page_end=last.page_no if last.page_no != first.page_no else None,
        bbox=bbox,
        source_text=text,
    )


def _build_heading_page_map(doc) -> dict[str, dict]:
    """Build a map of section heading text → page/level info from provenance."""
    heading_map = {}
    for item, _level in doc.iterate_items():
        if isinstance(item, SectionHeaderItem) and item.prov and item.text:
            prov = item.prov[0]
            heading_map[item.text] = {
                "page_no": prov.page_no,
                "level": item.level,
                "bbox": [prov.bbox.l, prov.bbox.t, prov.bbox.r, prov.bbox.b],
            }
    return heading_map


@mlflow.trace(name="docling_agent")
def docling_agent(state: dict) -> dict:
    """Convert CPG PDF to markdown and Docling JSON with provenance data."""
    logger.info("── Docling Agent ──")
    pdf_path = state["pdf_path"]
    output_dir = state.get("output_dir", "output")

    logger.info("Parsing PDF with Docling: %s", pdf_path)
    from docling.document_converter import PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.base_models import InputFormat
    pipeline_options = PdfPipelineOptions(do_ocr=False)
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )
    result = converter.convert(str(pdf_path))
    doc = result.document

    markdown = doc.export_to_markdown()
    docling_json = doc.export_to_dict()

    heading_page_map = _build_heading_page_map(doc)
    page_count = len(doc.pages)

    write_artifact(output_dir, "parsed.md", markdown)
    write_artifact(output_dir, "heading-page-map.json", heading_page_map)

    logger.info(
        "Docling parsed %d pages, %d headings, %d chars of markdown",
        page_count, len(heading_page_map), len(markdown),
    )

    return {
        "markdown": markdown,
        "docling_json": docling_json,
    }
