#!/usr/bin/env python3
"""Benchmark runner (RHAIENG-6461 P1c).

Runs ``metrics.score_pdf`` over a selected PDF set and writes both a
machine-readable ``report.json`` and a human-readable ``report.md`` to
``working/benchmarks/parsing/reports/`` (gitignored).

Sets:
    --synthetic   the checked-in synthetic corpus (NO network; CI-safe)
    --real        downloaded real CPGs under working/benchmarks/parsing/real/
                  (local only)
    --all         both

The synthetic path has no network dependency beyond Docling's local model
cache and is the target CI runs.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# cpg-ingester/tests/benchmarks/parsing -> repo root
REPO_ROOT = HERE.parents[3]
SYNTHETIC_DIR = HERE / "synthetic"
REAL_DIR = REPO_ROOT / "working" / "benchmarks" / "parsing" / "real"
REPORTS_DIR = REPO_ROOT / "working" / "benchmarks" / "parsing" / "reports"

sys.path.insert(0, str(HERE))
import metrics as metrics_mod  # noqa: E402


def _discover(directory: Path) -> list[tuple[Path, Path | None]]:
    """Return (pdf, groundtruth_or_None) pairs for a directory."""
    pairs = []
    if not directory.exists():
        return pairs
    for pdf in sorted(directory.glob("*.pdf")):
        gt = pdf.with_suffix(".groundtruth.json")
        pairs.append((pdf, gt if gt.exists() else None))
    return pairs


def _run_set(label: str, pairs, *, classify: bool) -> list[dict]:
    rows = []
    for pdf, gt in pairs:
        print(f"[{label}] parsing {pdf.name} ...", flush=True)
        try:
            m = metrics_mod.score_pdf(
                pdf, str(gt) if gt else None, do_ocr=False, classify_pictures=classify
            )
            m["set"] = label
            m["error"] = None
        except Exception as exc:  # keep the run resilient
            m = {"pdf": pdf.name, "set": label, "error": repr(exc)}
        rows.append(m)
    return rows


def _fmt(v):
    return "-" if v is None else v


def _markdown_report(rows: list[dict], generated_at: str) -> str:
    lines = [
        "# CPG Docling Parse-Quality Benchmark Report",
        "",
        f"_Generated: {generated_at}_",
        "",
        "Baseline metrics for the Docling parse stage (RHAIENG-6461). "
        "Ground-truth-dependent columns (heading/table recovery) are only "
        "populated for the synthetic set, which ships with sidecars.",
        "",
        "## Metric summary",
        "",
        "| set | pdf | archetype | pages | total_chars | text_yield (chars/pg) | headings | table cells | figures | scanned? |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r.get("error"):
            lines.append(
                f"| {r.get('set','-')} | {r['pdf']} | ERROR | - | - | - | - | - | - | - |"
            )
            continue
        hr = r.get("heading_recovery")
        hcell = (
            f"{r.get('headings_found','-')}/{r.get('headings_expected','-')} "
            f"({hr:.0%})" if hr is not None else "-"
        )
        tr = r.get("table_recovery")
        tcell = (
            f"{r.get('cells_detected','-')}/{r.get('cells_expected','-')} "
            f"({tr:.0%})" if tr is not None else str(r.get("cells_detected", "-"))
        )
        lines.append(
            f"| {r.get('set','-')} | {r['pdf']} | {_fmt(r.get('archetype'))} | "
            f"{_fmt(r.get('page_count'))} | {_fmt(r.get('total_chars'))} | "
            f"{_fmt(r.get('text_yield'))} | {hcell} | {tcell} | "
            f"{_fmt(r.get('figure_count'))} | {r.get('likely_scanned')} |"
        )

    # Notes on flowchart docs and any errors
    lines += ["", "## Notes", ""]
    for r in rows:
        if r.get("error"):
            lines.append(f"- **{r['pdf']}**: ERROR — `{r['error']}`")
            continue
        notes = []
        if r.get("headings_missing"):
            notes.append(f"missing headings: {r['headings_missing']}")
        if r.get("flowchart_nodes_expected"):
            notes.append(
                f"flowchart ground truth: {r['flowchart_nodes_expected']} nodes / "
                f"{r['flowchart_edges_expected']} edges (figure detected as "
                f"{r.get('figure_count')} picture(s); interpretation is P5)"
            )
        if r.get("likely_scanned"):
            notes.append("LIKELY SCANNED (low text yield; OCR is P4)")
        if notes:
            lines.append(f"- **{r['pdf']}**: " + "; ".join(notes))
    lines.append("")
    lines += [
        "## How to read these metrics",
        "",
        "- **text_yield** — extracted characters per page. Very low (< "
        f"{metrics_mod.LIKELY_SCANNED_CPP}) flags a likely-scanned PDF.",
        "- **heading recovery** — fraction of ground-truth section headings found "
        "in the parse output.",
        "- **table cells** — detected structured cells vs. ground-truth cell count.",
        "- **figures** — picture regions Docling detected (content interpretation "
        "is a later phase, P5).",
        "- **scanned?** — heuristic low-yield flag (the trigger P4's conditional "
        "OCR will consume).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--synthetic", action="store_true", help="synthetic corpus (CI-safe)")
    g.add_argument("--real", action="store_true", help="downloaded real CPGs (local)")
    g.add_argument("--all", action="store_true", help="both sets")
    ap.add_argument(
        "--classify", action="store_true",
        help="enable Docling picture classification (needs models; off by default "
             "to match production baseline)",
    )
    args = ap.parse_args()

    pairs_synth = _discover(SYNTHETIC_DIR)
    pairs_real = _discover(REAL_DIR)

    rows: list[dict] = []
    if args.synthetic or args.all:
        if not pairs_synth:
            print("No synthetic PDFs found — run generate_synthetic.py first.", file=sys.stderr)
            return 2
        rows += _run_set("synthetic", pairs_synth, classify=args.classify)
    if args.real or args.all:
        if not pairs_real:
            print(
                f"No real CPGs found in {REAL_DIR}. Run fetch-benchmark-cpgs.sh "
                "first (real set is local-only, never committed).",
                file=sys.stderr,
            )
            if args.real:
                return 2
        else:
            rows += _run_set("real", pairs_real, classify=args.classify)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    report_json = {
        "generated_at": generated_at,
        "likely_scanned_threshold_cpp": metrics_mod.LIKELY_SCANNED_CPP,
        "results": rows,
    }
    (REPORTS_DIR / "report.json").write_text(json.dumps(report_json, indent=2) + "\n")
    (REPORTS_DIR / "report.md").write_text(_markdown_report(rows, generated_at))

    print(f"\nWrote:\n  {REPORTS_DIR / 'report.json'}\n  {REPORTS_DIR / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
