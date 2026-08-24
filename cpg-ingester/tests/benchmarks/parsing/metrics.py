#!/usr/bin/env python3
"""Docling parse-quality metrics for the CPG benchmark (RHAIENG-6461).

Measures the **production** parser: converter construction, the scanned-page
threshold, and picture classification are all imported from ``cpg_ingester``
rather than mirrored here, so the benchmark can never silently drift from what
ships (the earlier "stay decoupled" copy had already drifted three ways —
``images_scale``, the threshold constant, and the deprecated ``.annotations``
read). ``interpret_metrics.py`` already imports the production node, so there is
no dependency-edge purity left to protect.

Public entry point:
    score_pdf(pdf_path, groundtruth_path=None, *, do_ocr=False,
              classify_pictures=False) -> dict

Returned metrics (keys always present; ground-truth-dependent ones are None
when no sidecar is supplied):
    text_yield          chars of extracted text per page
    total_chars, page_count
    heading_recovery    fraction (0..1) of expected headings found in output
    headings_found / headings_expected
    table_recovery      fraction (0..1) of expected table cells recovered
    tables_detected, cells_detected, cells_expected
    figure_count        number of picture regions detected
    figure_types        {class: count} when classification is enabled
    likely_scanned      bool: chars/page below LIKELY_SCANNED_CPP
    ocr_used            bool: whether OCR was enabled for this parse

No side effects (does not write files).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# The scanned-page threshold and picture-classification logic come straight from
# production so the benchmark measures exactly what ships.
from cpg_ingester.docling_convert import build_converter
from cpg_ingester.nodes.docling_agent import (
    LIKELY_SCANNED_CHARS_PER_PAGE as LIKELY_SCANNED_CPP,
    _picture_classification,
)


def _build_converter(do_ocr: bool = False, classify_pictures: bool = False):
    """Return the production Docling converter (see ``docling_convert``).

    ``classify_pictures`` maps to production ``extract_figures`` (picture-image
    generation + classification, at the production ``images_scale``).
    """
    return build_converter(do_ocr=do_ocr, extract_figures=classify_pictures)


def _normalize(text: str) -> str:
    """Lowercase, drop leading section numbering, collapse non-alphanumerics."""
    text = text.strip().lower()
    text = re.sub(r"^[\d.]+\s*", "", text)  # strip "1. " / "2.3 " prefixes
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _count_table_cells(doc) -> tuple[int, int]:
    """Return (tables_detected, total_cells_detected)."""
    tables = getattr(doc, "tables", []) or []
    total = 0
    for t in tables:
        data = getattr(t, "data", None)
        nr = getattr(data, "num_rows", None) if data is not None else None
        nc = getattr(data, "num_cols", None) if data is not None else None
        if nr and nc:
            total += int(nr) * int(nc)
        else:
            cells = getattr(data, "table_cells", None) if data is not None else None
            if cells:
                total += len(cells)
    return len(tables), total


def _figure_info(doc):
    pics = getattr(doc, "pictures", []) or []
    types: dict[str, int] = {}
    for p in pics:
        # Same classification extraction production uses (non-deprecated
        # get_annotations, same top-class selection).
        cls, _conf = _picture_classification(p)
        types[cls or "unclassified"] = types.get(cls or "unclassified", 0) + 1
    return len(pics), types


def _collect_headings(doc) -> list[str]:
    headings = []
    for item in getattr(doc, "texts", []) or []:
        label = getattr(item, "label", None)
        label = getattr(label, "value", label)
        if label in ("section_header", "title"):
            txt = getattr(item, "text", "") or ""
            if txt.strip():
                headings.append(txt.strip())
    return headings


def score_pdf(
    pdf_path,
    groundtruth_path: Optional[str] = None,
    *,
    do_ocr: bool = False,
    classify_pictures: bool = False,
) -> dict:
    import json

    pdf_path = Path(pdf_path)
    converter = _build_converter(do_ocr=do_ocr, classify_pictures=classify_pictures)
    result = converter.convert(str(pdf_path))
    doc = result.document

    markdown = doc.export_to_markdown() or ""
    page_count = len(getattr(doc, "pages", {}) or {}) or 1
    total_chars = len(markdown)
    text_yield = total_chars / page_count if page_count else 0.0

    tables_detected, cells_detected = _count_table_cells(doc)
    figure_count, figure_types = _figure_info(doc)
    detected_headings = _collect_headings(doc)

    metrics = {
        "pdf": pdf_path.name,
        "page_count": page_count,
        "total_chars": total_chars,
        "text_yield": round(text_yield, 1),
        "tables_detected": tables_detected,
        "cells_detected": cells_detected,
        "figure_count": figure_count,
        "figure_types": figure_types,
        "headings_detected_count": len(detected_headings),
        "likely_scanned": text_yield < LIKELY_SCANNED_CPP,
        "ocr_used": do_ocr,
        # ground-truth-dependent (filled below if a sidecar is present)
        "heading_recovery": None,
        "headings_found": None,
        "headings_expected": None,
        "table_recovery": None,
        "cells_expected": None,
        "archetype": None,
    }

    if groundtruth_path and Path(groundtruth_path).exists():
        gt = json.loads(Path(groundtruth_path).read_text())
        metrics["archetype"] = gt.get("archetype")

        expected_headings = gt.get("headings", []) or []
        norm_output = _normalize(markdown)
        norm_detected = [_normalize(h) for h in detected_headings]
        found = 0
        missing = []
        for h in expected_headings:
            nh = _normalize(h)
            if nh and (nh in norm_output or any(nh in d or d in nh for d in norm_detected if d)):
                found += 1
            else:
                missing.append(h)
        metrics["headings_expected"] = len(expected_headings)
        metrics["headings_found"] = found
        metrics["headings_missing"] = missing
        metrics["heading_recovery"] = (
            round(found / len(expected_headings), 3) if expected_headings else None
        )

        cells_expected = gt.get("table_cells", 0) or 0
        metrics["cells_expected"] = cells_expected
        if cells_expected:
            metrics["table_recovery"] = round(min(cells_detected, cells_expected) / cells_expected, 3)
        else:
            metrics["table_recovery"] = None

        # Ground truth also carries page_count; report the delta for visibility.
        metrics["page_count_expected"] = gt.get("page_count")
        metrics["flowchart_nodes_expected"] = len(gt.get("flowchart_nodes", []) or [])
        metrics["flowchart_edges_expected"] = len(gt.get("flowchart_edges", []) or [])

    return metrics


if __name__ == "__main__":  # simple manual invocation
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Score one PDF with Docling.")
    ap.add_argument("pdf")
    ap.add_argument("--groundtruth", default=None)
    ap.add_argument("--ocr", action="store_true")
    ap.add_argument("--classify", action="store_true")
    a = ap.parse_args()
    gt = a.groundtruth
    if gt is None:
        cand = Path(a.pdf).with_suffix(".groundtruth.json")
        gt = str(cand) if cand.exists() else None
    print(json.dumps(score_pdf(a.pdf, gt, do_ocr=a.ocr, classify_pictures=a.classify), indent=2))
