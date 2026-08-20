"""Docling Agent — converts CPG PDF to markdown + JSON with provenance data."""

import logging
from pathlib import Path

import mlflow
from docling_core.types.doc import DocItem, SectionHeaderItem, TextItem

from cpg_contracts import SourceLocation
from cpg_ingester.docling_convert import build_converter
from cpg_ingester.output import write_artifact

logger = logging.getLogger(__name__)

# Below this many characters of extracted text per page, a PDF is likely
# scanned/image-only and needs OCR. Consumed by the conditional-OCR re-parse
# (plan P4); for now it is a telemetry signal only.
LIKELY_SCANNED_CHARS_PER_PAGE = 100


def _parse_telemetry(doc, markdown: str, page_count: int) -> dict:
    """Compute parse-quality telemetry for observability (plan P2.2).

    Log-only for now — does not alter the node's return contract.
    """
    chars = len(markdown)
    chars_per_page = chars / page_count if page_count else 0.0
    return {
        "page_count": page_count,
        "chars": chars,
        "chars_per_page": round(chars_per_page, 1),
        "heading_count": sum(
            1 for item, _ in doc.iterate_items() if isinstance(item, SectionHeaderItem)
        ),
        "table_count": len(getattr(doc, "tables", []) or []),
        "figure_count": len(getattr(doc, "pictures", []) or []),
        "likely_scanned": page_count > 0
        and chars_per_page < LIKELY_SCANNED_CHARS_PER_PAGE,
    }


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
    converter = build_converter(do_ocr=False)
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

    telemetry = _parse_telemetry(doc, markdown, page_count)
    logger.info("Parse telemetry: %s", telemetry)
    if telemetry["likely_scanned"]:
        logger.warning(
            "PDF appears scanned/image-only (%.1f chars/page < %d) — OCR "
            "re-parse will be needed (plan P4)",
            telemetry["chars_per_page"], LIKELY_SCANNED_CHARS_PER_PAGE,
        )
    span = mlflow.get_current_active_span()
    if span is not None:
        span.set_attributes({f"parse.{k}": v for k, v in telemetry.items()})

    return {
        "markdown": markdown,
        "docling_json": docling_json,
    }
