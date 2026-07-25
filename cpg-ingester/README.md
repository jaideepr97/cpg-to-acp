# Clinical Practice Guideline Ingester

Multi-agent pipeline that parses CPG documents and extracts both computable decision logic (DMN) and narrative recommendations for the acp-writer.

## Architecture

Two-phase pipeline built with LangGraph:

```
Phase 1 — Analysis (sequential):
  Docling Agent → Structure Analyzer → Content Filter →
  Item Identifier ↔ Classification Reviewer → Metadata Extractor

Phase 2 — Generation (parallel with adversarial review):
  ┌─ DMN Creator → Syntax Validator → Semantic Reviewer ─┐
  │                                                       ├→ Assembly → Delivery
  └─ Rec Extractor → Schema Validator → Semantic Reviewer ┘
```

See `dev_docs/design/cpg-ingester-design.md` for the full design rationale.

## Two Outputs

1. **DMN decision tables** — Computable logic extracted from clinical decision algorithms, delivered to acp-writer's Drools/Kogito decision service (DMN 1.4).
2. **Recommendations** — Non-computable narrative content for RAG retrieval. Contract defined in `shared/cpg_contracts/` (`Recommendation`, `RecommendationBundle`).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e . -e ../shared
```

## Usage

### Full pipeline (new)

```bash
# Run the complete multi-agent pipeline
cpg-ingest data/synthetic-hypertension-cpg.pdf -o output/my-run

# With LLM and delivery configuration
cpg-ingest data/synthetic-hypertension-cpg.pdf \
  --litellm-url http://localhost:4000 \
  --model default \
  --acp-writer-url http://localhost:8082
```

Environment variables (alternative to CLI flags):
- `LITELLM_URL` — LiteLLM proxy URL (default: `http://localhost:4000`)
- `LLM_MODEL` — Model name (default: `default`)
- `LITELLM_API_KEY` — API key (default: `sk-change-me`)

### Output artifacts

Each run writes to an output directory (`output/<run-id>/`):

| File | Contents |
|---|---|
| `parsed.md` | Docling markdown output |
| `heading-page-map.json` | Section headings with page numbers |
| `section-map.json` | Section classifications (decision/recommendation/both/reference/skip) |
| `abbreviations.json` | Extracted abbreviation dictionary |
| `filtered.md` | Markdown after content filtering |
| `filter-report.json` | What was removed/restored by the filter |
| `manifest.json` | Item manifest with pre-assigned GUIDs |
| `metadata.json` | CPGMetadata |
| `classification-review-*.json` | Adversarial review reports |
| `dmn/*.dmn` | Generated DMN 1.4 XML files |
| `dmn-review-*.json` | DMN semantic review reports |
| `recommendations-*.json` | Extracted recommendations per section |
| `rec-review-*.json` | Recommendation semantic review reports |
| `recommendation-bundle.json` | Assembled RecommendationBundle |
| `assembly-report.json` | Integrity check results |
| `escalated-items.json` | Items needing human review (if any) |
| `delivery-status.json` | API delivery results |
| `run-summary.json` | Overall run summary |

### Legacy commands (still available)

```bash
# Parse only (Docling)
cpg-parse data/synthetic-hypertension-cpg.pdf -o output

# Extract DMN only (single-shot, no review)
cpg-extract-dmn output/synthetic-hypertension-cpg.md -o output \
  --litellm-url http://localhost:4000

# Deploy DMN to acp-writer
cpg-deploy-dmn output/decision-table-1.dmn --acp-writer-url http://localhost:8082
```

## Testing

```bash
# Run all unit tests (no LLM required)
pytest tests/

# Run integration tests (requires running LiteLLM)
LITELLM_URL=http://localhost:4000 pytest tests/ -k "Integration"
```

### Mock acp-writer receiver

For testing delivery without a running acp-writer:

```bash
python -m tests.mock_receiver --output-dir ./received --port 8082
```

## Review Strategy

Every extraction step has a two-layer review:

| Stage | Syntax (deterministic) | Semantic (LLM) |
|---|---|---|
| Content Filter | Keyword safety gate | — |
| Item Identification | — | Adversarial classification reviewer |
| Metadata | Pydantic + grading cross-check | — |
| DMN | XML/XSD/FEEL/structure checks | Claim-level source comparison |
| Recommendations | Pydantic/enum/cross-ref checks | Content faithfulness review |

Review loops retry up to 2 times, then escalate to human review.

## Tracing

All pipeline nodes are traced via `mlflow.langchain.autolog()`. Set `MLFLOW_TRACKING_URI` to point to your MLflow server, or traces will be stored locally.

## Data

- `data/synthetic-hypertension-cpg.pdf` — Synthetic CPG for testing
- `data/golden/` — Golden DMN files for validation
