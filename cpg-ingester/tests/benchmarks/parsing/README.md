# CPG Docling Parse-Quality Benchmark

Objective yardstick for the Docling PDF-parse stage of `cpg-ingester`
(RHAIENG-6461, plan §P1). It measures how well Docling recovers text,
headings, tables, and figures from CPG PDFs so later phases (figure
extraction/interpretation, OCR) can be proven to *improve* against a baseline.

> This is the **parsing** benchmark. It lives under `cpg-ingester/tests/benchmarks/`,
> one subfolder per benchmark (e.g. a future `benchmarks/dmn/` for DMN
> generation). Keep each benchmark self-contained in its own subfolder.

> **COPYRIGHT / COMMIT POLICY — read first**
>
> **No real third-party CPG PDF is ever committed to this repository.** This is a
> uniform rule with no per-document license adjudication — it applies even to
> U.S.-federal public-domain guidelines. Real CPGs are downloaded on demand into
> the **gitignored** `working/benchmarks/parsing/real/` directory by
> `fetch-benchmark-cpgs.sh`. Only the **synthetic** corpus (which we author) and
> the manifest/scripts are committed.

## Layout

```
cpg-ingester/tests/benchmarks/parsing/
├── README.md                     # this file
├── requirements.txt              # benchmark-only deps (reportlab, PyMuPDF, PyYAML)
├── generate_synthetic.py         # authors the synthetic corpus (deterministic)
├── synthetic/                    # COMMITTED: synthetic PDFs + ground-truth sidecars
│   ├── single-column.pdf         + .groundtruth.json
│   ├── two-column.pdf            + .groundtruth.json
│   ├── table-heavy.pdf           + .groundtruth.json
│   ├── flowchart-heavy.pdf       + .groundtruth.json
│   ├── mixed.pdf                 + .groundtruth.json
│   └── single-column-scanned.pdf + .groundtruth.json  (image-only; OCR fixture)
├── real-cpgs.manifest.yaml       # COMMITTED: manifest of real CPGs (URLs, no PDFs)
├── fetch-benchmark-cpgs.sh       # downloads real CPGs -> working/benchmarks/parsing/real/
├── metrics.py                    # self-contained Docling parse + scoring
├── run_benchmark.py              # runs metrics over a set, emits report.json + .md
└── run-benchmark.sh              # thin wrapper (uses the cpg-ingester venv)
```

Reports are written to
`working/benchmarks/parsing/reports/{report.json,report.md}` (gitignored).

## Prerequisites

Uses the existing `cpg-ingester` venv (where Docling is installed). Install the
benchmark-only extras once:

```bash
cpg-ingester/.venv/bin/pip install -r cpg-ingester/tests/benchmarks/parsing/requirements.txt
```

The scripts call `cpg-ingester/.venv/bin/python` by default. Point them at a
different interpreter with `BENCH_PYTHON=/path/to/python`.

> First Docling run downloads the layout + TableFormer models into the venv's
> HuggingFace cache. Allow a little extra time on the very first parse.

## 1. Generate the synthetic corpus

```bash
cpg-ingester/.venv/bin/python cpg-ingester/tests/benchmarks/parsing/generate_synthetic.py
```

Produces 5 born-digital PDFs + 1 image-only "scanned" variant, each with a
`*.groundtruth.json` sidecar, under `synthetic/`.

**Determinism:** generation is fully reproducible — `reportlab` invariant mode,
a fixed random seed, fixed PDF metadata/dates, and a pinned PDF `/ID` on the
rasterized scanned variant. Re-running produces **byte-identical** PDFs (verify
with `git status` — no diff after regenerating). This keeps the committed
binaries churn-free.

### Ground-truth sidecar schema

```jsonc
{
  "name": "table-heavy.pdf",
  "archetype": "table-heavy",
  "born_digital": true,
  "page_count": 1,                 // factual, read back from the rendered PDF
  "headings": ["Dosing Recommendations", ...],
  "tables": [{"rows": 5, "cols": 5, "cells": 25}, ...],
  "table_cells": 50,               // total across all tables
  "flowchart_nodes": [...],        // flowchart docs only
  "flowchart_edges": [["d1","a1","Yes"], ...]
}
```

## 2. Fetch real CPGs (local realism, never committed)

```bash
./cpg-ingester/tests/benchmarks/parsing/fetch-benchmark-cpgs.sh
```

Reads `real-cpgs.manifest.yaml`, downloads each entry into
`working/benchmarks/parsing/real/`, verifies `sha256` when pinned (records the observed
hash when the manifest says `TBD`), and prints a **manual-fallback** message for
any URL that 404s or blocks scripted fetch (e.g. cdc.gov returns 403 to
non-browser agents — open the URL in a browser, save to the printed path, and
re-run). Idempotent and safe to re-run.

To pin a hash: run the fetch once, copy the printed `sha256` into the manifest's
`sha256:` field for that entry.

## 3. Run the benchmark

```bash
# Synthetic only — NO network, CI-safe:
./cpg-ingester/tests/benchmarks/parsing/run-benchmark.sh --synthetic

# Downloaded real CPGs (local only):
./cpg-ingester/tests/benchmarks/parsing/run-benchmark.sh --real

# Both:
./cpg-ingester/tests/benchmarks/parsing/run-benchmark.sh --all
```

Outputs `working/benchmarks/parsing/reports/report.json` (machine-readable) and
`report.md` (human-readable). The `--synthetic` path has no network dependency
beyond Docling's local model cache and is the intended CI target.

Picture extraction + classification is **on by default** to match the production
parser (plan P3). Pass `--no-classify` to measure the pre-P3 baseline (parse
without the `picture_classifier` model), e.g. for a before/after comparison.

## Metrics — what they mean

| Metric | Meaning |
|---|---|
| **text_yield** | Extracted characters per page. Very low (< 100) → likely scanned. |
| **total_chars / page_count** | Raw extracted markdown length and page count. |
| **heading_recovery** | Fraction of ground-truth section headings found in output (synthetic only). |
| **table_recovery** | Detected structured table cells vs. ground-truth cell count (synthetic only). |
| **figure_count / figure_types** | Picture regions detected + their predicted classes (classification on by default; use `--no-classify` to skip). Figure *content* interpretation is a later phase (P5) — this only measures detection. |
| **likely_scanned** | Heuristic low-yield flag; the trigger the conditional-OCR phase (P4) will consume. |
| **ocr_used** | Whether OCR was enabled for this parse (baseline: false). |

### Interpreting the baseline

- Born-digital synthetic docs should show ~100% heading and table recovery and
  healthy text yield.
- The **scanned** variant should show `text_yield ≈ 0`, `likely_scanned = true`,
  and 0% heading recovery — this is the OCR-gap the harness is meant to expose.
  It is expected to fail at baseline and to recover once OCR (P4) lands.
- Flowchart docs detect the flowchart as **1 picture** but recover none of its
  node/edge structure as text — the figure-interpretation gap (P5).

## Notes / caveats

- `metrics.py` builds its own Docling `DocumentConverter` inline and does **not**
  import `cpg_ingester` — the harness is decoupled from production code.
- Heading recovery uses normalized substring matching (case-, numbering-, and
  punctuation-insensitive), so it is a recall proxy rather than an exact match.
- Table recovery is capped at 100% per doc (`min(detected, expected)`), so it
  does not reward over-segmentation of cells.
