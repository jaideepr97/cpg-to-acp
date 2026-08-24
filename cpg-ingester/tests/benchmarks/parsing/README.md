# CPG Docling Parse-Quality Benchmark

Objective yardstick for the Docling PDF-parse stage of `cpg-ingester`
(RHAIENG-6461). It measures how well Docling recovers text,
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
│   ├── multi-figure.pdf          + .groundtruth.json  (two DIFFERENT flowcharts; figure-placement fixture)
│   └── single-column-scanned.pdf + .groundtruth.json  (image-only; OCR fixture)
├── real-cpgs.manifest.yaml       # COMMITTED: manifest of real CPGs (URLs, no PDFs)
├── fetch-benchmark-cpgs.sh       # downloads real CPGs -> working/benchmarks/parsing/real/
├── metrics.py                    # scores the production Docling parser
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

Produces 6 born-digital PDFs + 1 image-only "scanned" variant, each with a
`*.groundtruth.json` sidecar, under `synthetic/`.

The `multi-figure.pdf` fixture embeds **two different** flowcharts (Condition C
treatment vs. AFib anticoagulation), each under its own heading. It exists to
verify figure↔location correlation: Docling preserves reading order in
`docling_json.body.children` (e.g. `…heading A → #/pictures/0 → heading B →
#/pictures/1 → Notes`), so figure interpretation anchors on the picture's
`self_ref`/position, **not** the anonymous `<!-- image -->` markdown comment.
Its sidecar adds a `figures[]` array with per-figure `index`, `heading`, and
`flowchart_nodes/edges` for scoring placement (the top-level `flowchart_*` keys
hold the aggregate across both charts).

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
parser. Pass `--no-classify` to measure the pre-classification baseline (parse
without the `picture_classifier` model), e.g. for a before/after comparison.

Pass `--ocr` to force RapidOCR on for every PDF, mirroring the OCR
engine the production conditional re-parse uses. Baseline runs keep OCR off;
use `--ocr` to measure the recovery on scanned fixtures. The report header
records the OCR mode, so preserve baseline vs. OCR runs under distinct names
for a before/after comparison, e.g.:

```bash
run-benchmark.sh --synthetic            # baseline → report.md
cp .../report.md .../report-baseline.md
run-benchmark.sh --synthetic --ocr      # OCR on   → report.md
cp .../report.md .../report-ocr.md
```

> **Note:** forced full-page OCR *reduces* text yield on born-digital PDFs
> (the native text layer beats OCR). This is why the production node only OCRs
> when `likely_scanned` and keeps whichever pass extracts more text — the
> `--ocr` flag here forces it unconditionally purely for measurement.

### Figure interpretation (`--interpret`) — LIVE, opt-in

`--interpret` measures figure *content* recovery, not just detection: it runs
the **production** `figure_interpreter` node (via `interpret_metrics.py`) over
each PDF's figures and scores node/edge recovery + Mermaid validity against the
per-figure ground truth. Because interpreting a figure calls a vision model,
this is **off by default** (the plain `--synthetic` run stays offline/CI-safe)
and requires the LLM env. Example against direct OpenAI:

```bash
LITELLM_URL=https://api.openai.com LLM_MODEL=gpt-5.6 LLM_API_KEY=$OPENAI_API_KEY \
  ./cpg-ingester/tests/benchmarks/parsing/run-benchmark.sh --synthetic --interpret
```

The report gains a "Figure interpretation" table (per figure: Mermaid validity,
node match/gt, edge rec/gt, and which ground-truth block it was scored against).
Unlike `metrics.py`, `interpret_metrics.py` intentionally imports production code
(`docling_agent` + `figure_interpreter`) — the point is to score the real node.

## Metrics — what they mean

| Metric | Meaning |
|---|---|
| **text_yield** | Extracted characters per page. Very low (< 100) → likely scanned. |
| **total_chars / page_count** | Raw extracted markdown length and page count. |
| **heading_recovery** | Fraction of ground-truth section headings found in output (synthetic only). |
| **table_recovery** | Detected structured table cells vs. ground-truth cell count (synthetic only). |
| **figure_count / figure_types** | Picture regions detected + their predicted classes (classification on by default; use `--no-classify` to skip). Figure *content* interpretation is a separate, later stage — this only measures detection. |
| **likely_scanned** | Heuristic low-yield flag; the trigger the conditional-OCR re-parse consumes. |
| **ocr_used** | Whether OCR was enabled for this parse (baseline: false). |

### Interpreting the baseline

- Born-digital synthetic docs should show ~100% heading and table recovery and
  healthy text yield.
- The **scanned** variant should show `text_yield ≈ 0`, `likely_scanned = true`,
  and 0% heading recovery — this is the OCR-gap the harness is meant to expose.
  It is expected to fail at baseline and to recover once OCR is enabled.
- Flowchart docs detect the flowchart as **1 picture** but recover none of its
  node/edge structure as text — the figure-interpretation gap.

## Notes / caveats

- `metrics.py` imports the **production** parser from `cpg_ingester`
  (`docling_convert.build_converter`, the `LIKELY_SCANNED_CHARS_PER_PAGE`
  threshold, and `_picture_classification`) so the benchmark measures exactly
  what ships and can never silently drift from it.
- Heading recovery uses normalized substring matching (case-, numbering-, and
  punctuation-insensitive), so it is a recall proxy rather than an exact match.
- Table recovery is capped at 100% per doc (`min(detected, expected)`), so it
  does not reward over-segmentation of cells.
