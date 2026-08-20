#!/usr/bin/env python3
"""Generate the synthetic CPG benchmark corpus (RHAIENG-6461 P1a).

Produces 5 born-digital PDFs spanning CPG archetypes plus 1 image-only
"scanned" variant, each with a ground-truth JSON sidecar. Output lands in
``synthetic/`` next to this file and IS committed to git.

Determinism / reproducibility (hard requirement):
  * ``reportlab.rl_config.invariant = 1`` -> fixed PDF creation date + /ID.
  * ``random.seed(SEED)`` -> stable content ordering.
  * PyMuPDF scanned variant: fixed metadata dates, no incremental xref,
    deterministic PNG raster at a fixed DPI.
Re-running this script MUST produce byte-identical PDFs (verified by
generating twice and diffing). If you change layout, regenerate and commit.

Usage:
    cpg-ingester/.venv/bin/python cpg-ingester/tests/benchmark/generate_synthetic.py

The ground-truth sidecar schema (``<name>.groundtruth.json``):
    {
      "name", "archetype", "born_digital" (bool),
      "page_count",                # factual, read back from the rendered PDF
      "headings": [str, ...],      # section headings expected in parse output
      "tables": [{"rows","cols","cells"}, ...],
      "table_cells": int,          # total across all tables
      "flowchart_nodes": [str],    # flowchart doc only
      "flowchart_edges": [[from,to,label]]  # flowchart doc only
    }
"""
from __future__ import annotations

import io
import json
import random
from pathlib import Path

# --- Determinism switch: MUST precede any reportlab document construction. ---
import reportlab.rl_config

reportlab.rl_config.invariant = 1  # fixed creation date + document /ID

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont

SEED = 20260820
OUT_DIR = Path(__file__).resolve().parent / "synthetic"

# Fixed document metadata so re-runs are byte-stable.
DOC_META = {
    "title": "Synthetic Clinical Practice Guideline (Benchmark Fixture)",
    "author": "cpg-to-acp benchmark harness",
    "subject": "RHAIENG-6461 Docling parse-quality benchmark",
    "creator": "generate_synthetic.py",
}

# ---------------------------------------------------------------------------
# Shared prose (deterministic clinical-sounding filler; not real guidance).
# ---------------------------------------------------------------------------
LOREM = (
    "This recommendation applies to adult patients presenting in the ambulatory "
    "setting. Clinicians should assess baseline risk before initiating therapy "
    "and reassess at each follow-up visit. Shared decision making is advised "
    "when the balance of benefits and harms is uncertain. The strength of this "
    "recommendation reflects moderate-certainty evidence derived from randomized "
    "controlled trials and well-conducted observational cohorts."
)
GRADE = (
    "Strength of recommendation: Strong. Certainty of evidence: Moderate (GRADE). "
    "Benefits are judged to outweigh harms for most patients in this population."
)


def _styles():
    ss = getSampleStyleSheet()
    body = ParagraphStyle(
        "CpgBody", parent=ss["BodyText"], fontName="Helvetica", fontSize=10,
        leading=13, alignment=TA_JUSTIFY, spaceAfter=6,
    )
    h1 = ParagraphStyle(
        "CpgH1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=15,
        leading=18, spaceBefore=12, spaceAfter=6,
    )
    h2 = ParagraphStyle(
        "CpgH2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12,
        leading=15, spaceBefore=10, spaceAfter=4,
    )
    small = ParagraphStyle(
        "CpgSmall", parent=body, fontSize=8, leading=10,
    )
    return {"body": body, "h1": h1, "h2": h2, "small": small}


def _set_pdf_metadata(path: Path) -> None:
    """Reportlab already sets fixed dates under invariant mode; this only
    normalizes the Info dict fields we care about. No-op if identical."""
    # reportlab writes metadata at build time; nothing extra needed here.
    return None


# ---------------------------------------------------------------------------
# 1. Single-column
# ---------------------------------------------------------------------------
def build_single_column(path: Path) -> dict:
    styles = _styles()
    headings = [
        "1. Scope and Purpose",
        "2. Screening Recommendations",
        "3. Pharmacologic Management",
        "4. Monitoring and Follow-up",
    ]
    story = [Paragraph("Guideline for the Management of Chronic Condition A", styles["h1"])]
    story.append(Paragraph(GRADE, styles["small"]))
    story.append(Spacer(1, 8))
    for h in headings:
        story.append(Paragraph(h, styles["h2"]))
        for _ in range(3):
            story.append(Paragraph(LOREM, styles["body"]))
    doc = SimpleDocTemplate(
        str(path), pagesize=LETTER, title=DOC_META["title"],
        author=DOC_META["author"], subject=DOC_META["subject"],
        creator=DOC_META["creator"],
        leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch,
    )
    doc.build(story)
    return {
        "archetype": "single-column",
        "headings": headings,
        "tables": [],
        "flowchart_nodes": [],
        "flowchart_edges": [],
    }


# ---------------------------------------------------------------------------
# 2. Dense two-column journal
# ---------------------------------------------------------------------------
def build_two_column(path: Path) -> dict:
    styles = _styles()
    headings = [
        "Abstract",
        "Introduction",
        "Methods",
        "Evidence Synthesis",
        "Recommendation Statements",
        "Discussion",
    ]
    body = ParagraphStyle("dense", parent=styles["body"], fontSize=9, leading=11, spaceAfter=4)

    doc = BaseDocTemplate(
        str(path), pagesize=LETTER, title=DOC_META["title"],
        author=DOC_META["author"], subject=DOC_META["subject"],
        creator=DOC_META["creator"],
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    )
    gap = 0.3 * inch
    col_w = (doc.width - gap) / 2.0
    f1 = Frame(doc.leftMargin, doc.bottomMargin, col_w, doc.height, id="c1")
    f2 = Frame(doc.leftMargin + col_w + gap, doc.bottomMargin, col_w, doc.height, id="c2")
    doc.addPageTemplates([PageTemplate(id="TwoCol", frames=[f1, f2])])

    story = [Paragraph("A Systematic Review and Guideline for Condition B", styles["h1"])]
    for h in headings:
        story.append(Paragraph(h, styles["h2"]))
        for _ in range(4):
            story.append(Paragraph(LOREM + " " + LOREM, body))
    doc.build(story)
    return {
        "archetype": "two-column-dense",
        "headings": headings,
        "tables": [],
        "flowchart_nodes": [],
        "flowchart_edges": [],
    }


# ---------------------------------------------------------------------------
# 3. Table-heavy (dosing + monitoring)
# ---------------------------------------------------------------------------
def _dosing_table():
    header = ["Drug", "Starting Dose", "Titration", "Max Dose", "Renal Adjust"]
    rows = [
        ["Agent Alpha", "5 mg daily", "+5 mg q2wk", "40 mg/day", "eGFR<30: halve"],
        ["Agent Beta", "10 mg BID", "+10 mg q1wk", "80 mg/day", "No change"],
        ["Agent Gamma", "25 mg daily", "+25 mg q4wk", "100 mg/day", "eGFR<45: avoid"],
        ["Agent Delta", "2.5 mg daily", "+2.5 mg q2wk", "20 mg/day", "eGFR<15: avoid"],
    ]
    return [header] + rows


def _monitoring_table():
    header = ["Parameter", "Baseline", "Week 4", "Week 12", "Every 6 mo"]
    rows = [
        ["Serum potassium", "Yes", "Yes", "Yes", "Yes"],
        ["eGFR", "Yes", "Yes", "Yes", "Yes"],
        ["Blood pressure", "Yes", "Yes", "Yes", "Yes"],
        ["Liver function", "Yes", "No", "Yes", "Yes"],
    ]
    return [header] + rows


def build_table_heavy(path: Path) -> dict:
    styles = _styles()
    headings = ["Dosing Recommendations", "Monitoring Schedule", "Notes"]

    def styled(data):
        t = Table(data, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ecf0f1")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    dosing = _dosing_table()
    monitoring = _monitoring_table()

    story = [
        Paragraph("Pharmacologic Therapy Reference Tables", styles["h1"]),
        Paragraph(headings[0], styles["h2"]),
        Paragraph("Recommended starting doses and titration schedule.", styles["body"]),
        styled(dosing),
        Spacer(1, 14),
        Paragraph(headings[1], styles["h2"]),
        Paragraph("Laboratory and clinical monitoring cadence.", styles["body"]),
        styled(monitoring),
        Spacer(1, 14),
        Paragraph(headings[2], styles["h2"]),
        Paragraph(LOREM, styles["body"]),
    ]
    doc = SimpleDocTemplate(
        str(path), pagesize=LETTER, title=DOC_META["title"],
        author=DOC_META["author"], subject=DOC_META["subject"],
        creator=DOC_META["creator"],
        leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch,
    )
    doc.build(story)

    tables = [
        {"rows": len(dosing), "cols": len(dosing[0]), "cells": len(dosing) * len(dosing[0])},
        {"rows": len(monitoring), "cols": len(monitoring[0]),
         "cells": len(monitoring) * len(monitoring[0])},
    ]
    return {
        "archetype": "table-heavy",
        "headings": headings,
        "tables": tables,
        "flowchart_nodes": [],
        "flowchart_edges": [],
    }


# ---------------------------------------------------------------------------
# 4. Flowchart-heavy (raster flowchart embedded as an image)
# ---------------------------------------------------------------------------
# Node/edge spec drives both the drawing and the ground truth.
FLOWCHART_NODES = [
    {"id": "start", "kind": "start", "text": "Patient with Condition C", "xy": (300, 40), "wh": (240, 50)},
    {"id": "d1", "kind": "decision", "text": "Symptoms severe?", "xy": (300, 150), "wh": (200, 90)},
    {"id": "a1", "kind": "action", "text": "Start first-line therapy", "xy": (120, 300), "wh": (200, 60)},
    {"id": "a2", "kind": "action", "text": "Lifestyle counseling", "xy": (500, 300), "wh": (200, 60)},
    {"id": "d2", "kind": "decision", "text": "Response at 4 weeks?", "xy": (120, 430), "wh": (200, 90)},
    {"id": "a3", "kind": "action", "text": "Escalate to second-line", "xy": (120, 580), "wh": (220, 60)},
    {"id": "end", "kind": "end", "text": "Continue and monitor", "xy": (500, 580), "wh": (220, 60)},
]
FLOWCHART_EDGES = [
    ("start", "d1", ""),
    ("d1", "a1", "Yes"),
    ("d1", "a2", "No"),
    ("a1", "d2", ""),
    ("d2", "a3", "No"),
    ("d2", "end", "Yes"),
    ("a2", "end", ""),
]
CANVAS_WH = (820, 700)


def _font(size):
    # Try a real TTF for stable, legible glyphs; fall back to PIL default.
    for cand in [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if Path(cand).exists():
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _center_text(draw, cx, cy, text, font, fill=(0, 0, 0)):
    # wrap on spaces to keep within ~ node width
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if len(trial) > 18 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    try:
        line_h = font.getbbox("Ag")[3] + 2
    except Exception:
        line_h = 14
    total = line_h * len(lines)
    y = cy - total / 2
    for ln in lines:
        try:
            w = draw.textlength(ln, font=font)
        except Exception:
            w = len(ln) * 6
        draw.text((cx - w / 2, y), ln, font=font, fill=fill)
        y += line_h


def _draw_flowchart_png(scale: int = 2) -> bytes:
    W, H = CANVAS_WH[0] * scale, CANVAS_WH[1] * scale
    img = PILImage.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    font = _font(15 * scale)
    node_by_id = {n["id"]: n for n in FLOWCHART_NODES}

    def rect(n):
        cx, cy = n["xy"][0] * scale, n["xy"][1] * scale
        w, h = n["wh"][0] * scale, n["wh"][1] * scale
        return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    # edges first (so nodes overlay endpoints)
    for src, dst, label in FLOWCHART_EDGES:
        s, t = node_by_id[src], node_by_id[dst]
        x1, y1 = s["xy"][0] * scale, (s["xy"][1] + s["wh"][1] / 2) * scale
        x2, y2 = t["xy"][0] * scale, (t["xy"][1] - t["wh"][1] / 2) * scale
        d.line([(x1, y1), (x2, y2)], fill=(60, 60, 60), width=max(2, scale))
        # arrowhead
        d.polygon(
            [(x2, y2), (x2 - 5 * scale, y2 - 10 * scale), (x2 + 5 * scale, y2 - 10 * scale)],
            fill=(60, 60, 60),
        )
        if label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            _center_text(d, mx, my, label, font, fill=(180, 0, 0))

    # nodes
    for n in FLOWCHART_NODES:
        x0, y0, x1, y1 = rect(n)
        cx, cy = n["xy"][0] * scale, n["xy"][1] * scale
        if n["kind"] == "decision":
            d.polygon(
                [(cx, y0), (x1, cy), (cx, y1), (x0, cy)],
                fill=(255, 249, 196), outline=(120, 120, 0), width=max(2, scale),
            )
        elif n["kind"] in ("start", "end"):
            d.rounded_rectangle([x0, y0, x1, y1], radius=18 * scale,
                                fill=(200, 230, 201), outline=(56, 142, 60), width=max(2, scale))
        else:
            d.rectangle([x0, y0, x1, y1], fill=(187, 222, 251),
                        outline=(25, 118, 210), width=max(2, scale))
        _center_text(d, cx, cy, n["text"], font)

    buf = io.BytesIO()
    # optimize=True for stable, compact PNG; PNG has no timestamp by default here.
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def build_flowchart_heavy(path: Path) -> dict:
    styles = _styles()
    headings = ["Treatment Algorithm", "Algorithm Notes"]
    png = _draw_flowchart_png(scale=2)
    img_reader = io.BytesIO(png)
    # scale image to fit page width
    pil = PILImage.open(io.BytesIO(png))
    iw, ih = pil.size
    max_w = 6.3 * inch
    disp_w = max_w
    disp_h = max_w * ih / iw

    story = [
        Paragraph("Clinical Decision Algorithm for Condition C", styles["h1"]),
        Paragraph(headings[0], styles["h2"]),
        Paragraph("The following algorithm summarizes the stepwise approach.", styles["body"]),
        Image(img_reader, width=disp_w, height=disp_h),
        Spacer(1, 10),
        Paragraph(headings[1], styles["h2"]),
        Paragraph(LOREM, styles["body"]),
    ]
    doc = SimpleDocTemplate(
        str(path), pagesize=LETTER, title=DOC_META["title"],
        author=DOC_META["author"], subject=DOC_META["subject"],
        creator=DOC_META["creator"],
        leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch,
    )
    doc.build(story)
    return {
        "archetype": "flowchart-heavy",
        "headings": headings,
        "tables": [],
        "flowchart_nodes": [n["text"] for n in FLOWCHART_NODES],
        "flowchart_edges": [[s, t, lbl] for (s, t, lbl) in FLOWCHART_EDGES],
    }


# ---------------------------------------------------------------------------
# 5. Mixed (headings + table + flowchart + prose)
# ---------------------------------------------------------------------------
def build_mixed(path: Path) -> dict:
    styles = _styles()
    headings = [
        "1. Overview",
        "2. Risk Stratification Table",
        "3. Management Algorithm",
        "4. Follow-up",
    ]
    risk = [
        ["Risk Category", "eGFR", "Albuminuria", "Action"],
        ["Low", ">=60", "<30 mg/g", "Routine"],
        ["Moderate", "45-59", "30-300 mg/g", "Refer if progressing"],
        ["High", "<45", ">300 mg/g", "Nephrology referral"],
    ]
    t = Table(risk, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))

    png = _draw_flowchart_png(scale=2)
    pil = PILImage.open(io.BytesIO(png))
    iw, ih = pil.size
    disp_w = 5.2 * inch
    disp_h = disp_w * ih / iw

    story = [
        Paragraph("Integrated Guideline for Condition D", styles["h1"]),
        Paragraph(headings[0], styles["h2"]),
        Paragraph(LOREM, styles["body"]),
        Paragraph(headings[1], styles["h2"]),
        t,
        Spacer(1, 12),
        Paragraph(headings[2], styles["h2"]),
        Image(io.BytesIO(png), width=disp_w, height=disp_h),
        Spacer(1, 10),
        Paragraph(headings[3], styles["h2"]),
        Paragraph(LOREM, styles["body"]),
    ]
    doc = SimpleDocTemplate(
        str(path), pagesize=LETTER, title=DOC_META["title"],
        author=DOC_META["author"], subject=DOC_META["subject"],
        creator=DOC_META["creator"],
        leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch,
    )
    doc.build(story)
    return {
        "archetype": "mixed",
        "headings": headings,
        "tables": [{"rows": len(risk), "cols": len(risk[0]), "cells": len(risk) * len(risk[0])}],
        "flowchart_nodes": [n["text"] for n in FLOWCHART_NODES],
        "flowchart_edges": [[s, t, lbl] for (s, t, lbl) in FLOWCHART_EDGES],
    }


# ---------------------------------------------------------------------------
# Scanned variant: rasterize a born-digital PDF into an image-only PDF.
# ---------------------------------------------------------------------------
def build_scanned_from(src_pdf: Path, dst_pdf: Path, dpi: int = 150) -> None:
    import pymupdf as fitz  # PyMuPDF

    src = fitz.open(str(src_pdf))
    out = fitz.open()
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for page in src:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes("png")  # deterministic given fixed raster
        rect = page.rect
        newpage = out.new_page(width=rect.width, height=rect.height)
        newpage.insert_image(rect, stream=png_bytes)
    # Fixed metadata so re-runs are byte-stable.
    out.set_metadata({
        "title": DOC_META["title"] + " (scanned)",
        "author": DOC_META["author"],
        "subject": DOC_META["subject"],
        "creator": DOC_META["creator"],
        "producer": "PyMuPDF benchmark rasterizer",
        "creationDate": "D:20260820000000Z",
        "modDate": "D:20260820000000Z",
    })
    raw = out.tobytes(garbage=4, deflate=True)
    out.close()
    src.close()
    # PyMuPDF regenerates a random trailer /ID on every save; pin it so the
    # output is byte-stable across runs (only the /ID bytes are nondeterministic).
    import re

    fixed_id = b"/ID[<00000000000000000000000000000000><00000000000000000000000000000000>]"
    raw = re.sub(rb"/ID\[<[0-9A-Fa-f]+><[0-9A-Fa-f]+>\]", fixed_id, raw, count=1)
    dst_pdf.write_bytes(raw)


# ---------------------------------------------------------------------------
def _page_count(path: Path) -> int:
    import pymupdf as fitz
    d = fitz.open(str(path))
    n = d.page_count
    d.close()
    return n


def _write_sidecar(pdf_path: Path, meta: dict, born_digital: bool) -> None:
    gt = {
        "name": pdf_path.name,
        "archetype": meta["archetype"],
        "born_digital": born_digital,
        "page_count": _page_count(pdf_path),
        "headings": meta["headings"],
        "tables": meta["tables"],
        "table_cells": sum(t["cells"] for t in meta["tables"]),
        "flowchart_nodes": meta["flowchart_nodes"],
        "flowchart_edges": meta["flowchart_edges"],
    }
    side = pdf_path.with_suffix(".groundtruth.json")
    side.write_text(json.dumps(gt, indent=2, sort_keys=True) + "\n")


def main() -> None:
    random.seed(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    specs = [
        ("single-column.pdf", build_single_column),
        ("two-column.pdf", build_two_column),
        ("table-heavy.pdf", build_table_heavy),
        ("flowchart-heavy.pdf", build_flowchart_heavy),
        ("mixed.pdf", build_mixed),
    ]
    for name, fn in specs:
        p = OUT_DIR / name
        meta = fn(p)
        _write_sidecar(p, meta, born_digital=True)
        print(f"  wrote {name} ({_page_count(p)} pages)")

    # Scanned variant of single-column (same ground truth, image-only).
    sc_src = OUT_DIR / "single-column.pdf"
    sc_dst = OUT_DIR / "single-column-scanned.pdf"
    build_scanned_from(sc_src, sc_dst)
    # Reuse single-column ground truth but flag as not born-digital.
    src_gt = json.loads((sc_src.with_suffix(".groundtruth.json")).read_text())
    src_gt["name"] = sc_dst.name
    src_gt["archetype"] = "single-column-scanned"
    src_gt["born_digital"] = False
    src_gt["page_count"] = _page_count(sc_dst)
    (sc_dst.with_suffix(".groundtruth.json")).write_text(
        json.dumps(src_gt, indent=2, sort_keys=True) + "\n"
    )
    print(f"  wrote {sc_dst.name} ({_page_count(sc_dst)} pages, scanned/image-only)")

    print(f"Done. {len(specs) + 1} PDFs + sidecars in {OUT_DIR}")


if __name__ == "__main__":
    main()
