"""Docling Agent — converts CPG PDF to markdown + JSON with provenance data."""

import base64
import io
import logging
from pathlib import Path

import mlflow
from docling_core.types.doc import (
    DocItem,
    PictureItem,
    SectionHeaderItem,
    TextItem,
)

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


def _picture_classification(pic: PictureItem) -> tuple[str | None, float | None]:
    """Return the top predicted class name + confidence, or (None, None).

    Populated when the converter runs with ``do_picture_classification`` (plan
    P3). Uses ``get_annotations()`` (the ``.annotations`` attribute is
    deprecated in docling-core).
    """
    best_name, best_conf = None, None
    for ann in pic.get_annotations() or []:
        for cls in getattr(ann, "predicted_classes", None) or []:
            conf = getattr(cls, "confidence", None)
            if conf is not None and (best_conf is None or conf > best_conf):
                best_name, best_conf = getattr(cls, "class_name", None), conf
    return best_name, best_conf


def _extract_figures(doc, output_dir: str) -> tuple[list[dict], dict[str, str]]:
    """Pull each picture's bitmap, class, and provenance out of the document.

    Returns ``(figures, figure_images)`` where ``figures`` is a metadata index
    (``id``, ``page``, ``bbox``, ``classification``, ``confidence``, ``caption``,
    and a local ``image_filename`` when a bitmap was captured) and
    ``figure_images`` maps figure id → base64-PNG. The ingestion service moves
    those bitmaps to the artifact store and records an ``image_ref`` (plan P3.3);
    the interpreter (plan P5) consumes the index.

    Requires the converter to have run with ``extract_figures=True`` so picture
    images are generated; without it ``get_image`` returns ``None`` and only
    metadata is captured.
    """
    figures: list[dict] = []
    images: dict[str, str] = {}
    fig_dir = Path(output_dir) / "figures"

    for idx, pic in enumerate(getattr(doc, "pictures", []) or [], start=1):
        fid = f"fig-{idx:03d}"
        loc = _extract_source_location(pic)
        classification, confidence = _picture_classification(pic)
        entry: dict = {
            "id": fid,
            "page": loc.page_start if loc else None,
            "bbox": loc.bbox if loc else None,
            "classification": classification,
            "confidence": round(confidence, 3) if confidence is not None else None,
            "caption": pic.caption_text(doc) or "",
        }

        pil = pic.get_image(doc)
        if pil is not None:
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            png = buf.getvalue()
            fig_dir.mkdir(parents=True, exist_ok=True)
            (fig_dir / f"{fid}.png").write_bytes(png)
            entry["image_filename"] = f"figures/{fid}.png"
            images[fid] = base64.b64encode(png).decode("ascii")

        figures.append(entry)

    return figures, images


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

    # Figure extraction (plan P3): pull each picture's bitmap, class, and
    # provenance out BEFORE stripping images, so get_image() still resolves.
    figures, figure_images = _extract_figures(doc, output_dir)
    # Strip embedded picture bitmaps from the doc before serializing so
    # docling_json stays lean (~14x smaller on figure-heavy PDFs). The bitmaps
    # are preserved separately via the figures index + figure_images (MinIO).
    for pic in getattr(doc, "pictures", []) or []:
        pic.image = None
    docling_json = doc.export_to_dict()

    heading_page_map = _build_heading_page_map(doc)
    page_count = len(doc.pages)

    write_artifact(output_dir, "parsed.md", markdown)
    write_artifact(output_dir, "heading-page-map.json", heading_page_map)
    if figures:
        write_artifact(output_dir, "figures-index.json", figures)

    logger.info(
        "Docling parsed %d pages, %d headings, %d chars of markdown, %d figures",
        page_count, len(heading_page_map), len(markdown), len(figures),
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
        "figures": figures,
        "figure_images": figure_images,
    }
