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

## Web UI

A PatternFly 6 + React 19 SPA for uploading CPGs, monitoring pipeline progress, reviewing AI-extracted artifacts with cyclical feedback gates, and approving delivery.

### Screens

| Screen | Route | Purpose |
|---|---|---|
| Dashboard | `/` | List pipeline runs, status, rerun actions |
| Upload | `/upload` | Drag-and-drop PDF upload |
| Run Detail | `/runs/:id` | Live progress stepper, AI reasoning log, tabbed sub-views |
| Structure Review | `/runs/:id` (tab) | TreeView of CPG sections with classifications |
| Decision Review | `/runs/:id` (tab) | DMN models with decision tables, per-item feedback |
| Recommendation Review | `/runs/:id` (tab) | Recommendations with certainty grades, per-item feedback |
| Assembly Report | `/runs/:id` (tab) | Integrity checks, escalated items |
| Approval & Delivery | `/runs/:id` (tab) | Artifact delivery to acp-writer, per-artifact status |

Review screens support a **cyclical feedback pattern**: approve OR request changes with per-item comments. The pipeline regenerates incorporating feedback, then presents updated artifacts for re-review.

### Tech stack

- **PatternFly 6** — Red Hat design system (Page, Nav, Table, DataList, TreeView, ProgressStepper, CodeBlock, FileUpload, Modal, Skeleton, EmptyState)
- **React 19 + TypeScript** (strict mode)
- **Vite 6** — dev server on port 3003, proxies `/api` to BFF at `localhost:8095`
- **TanStack Query v5** — data fetching with adaptive polling (stops on errors, stops when no active runs)
- **react-router v7** — client-side routing

### Local development

```bash
cd cpg-ingester/ui
npm install
npm run dev          # http://localhost:3003
```

The UI proxies `/api/*` requests to the BFF (default `http://localhost:8095`). Start the BFF first (see below).

### Production build

The UI is built as a multi-stage Docker image: Node 22 Alpine for the build step, nginx-unprivileged for serving. nginx uses `envsubst` to resolve `${BFF_HOST}` at container startup, proxying `/api/` requests to the BFF pod.

```
cpg-ingester/ui/Containerfile       # Multi-stage build
cpg-ingester/ui/nginx.conf       # Template with ${BFF_HOST} substitution
```

## Backend-for-Frontend (BFF)

A FastAPI service that mediates between the SPA and SonataFlow/MinIO. The UI talks **only** to the BFF — never directly to SonataFlow or MinIO.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/runs` | List pipeline runs |
| `GET` | `/api/v1/runs/{id}` | Run detail with steps, artifacts, review state |
| `POST` | `/api/v1/upload` | Accept PDF upload, start pipeline |
| `POST` | `/api/v1/runs/{id}/review/{gate}` | Submit review decision (approve / request changes) |
| `POST` | `/api/v1/runs/{id}/rerun` | Re-run a completed or failed pipeline |
| `GET` | `/api/v1/runs/{id}/artifacts/{path}` | Fetch artifact from storage |
| `GET` | `/health` | Health check |

### Mock mode

When `SONATAFLOW_URL` and `MINIO_ENDPOINT` are **not** configured, the BFF automatically loads mock data from `cpg_ingester/mocks/`. This provides 5 sample runs at different pipeline stages so the UI can be developed and demonstrated without real infrastructure.

Mock data lives in its own package:

```
src/cpg_ingester/mocks/
  ├── __init__.py
  ├── data.py       # Mock runs, artifacts, decisions, recommendations
  └── router.py     # FastAPI router with mock endpoint implementations
```

The BFF uses a guarded import — if the mocks package is absent (e.g., stripped from a production image), the BFF logs a warning and starts without mock endpoints.

### Running locally

```bash
cd cpg-ingester
python3 -m venv .venv && source .venv/bin/activate
pip install -e . -e ../shared
pip install fastapi uvicorn python-multipart

uvicorn cpg_ingester.services.bff:app --host 0.0.0.0 --port 8095 --reload
```

Without `SONATAFLOW_URL` / `MINIO_ENDPOINT` set, the BFF starts in mock mode automatically.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SONATAFLOW_URL` | _(empty)_ | SonataFlow base URL. When absent, enables mock mode |
| `MINIO_ENDPOINT` | _(empty)_ | MinIO endpoint. When absent, enables mock mode |
| `MLFLOW_TRACKING_URI` | _(empty)_ | MLflow tracing endpoint |

## Deployment

### OpenShift (Helm)

The UI and BFF are deployed as separate pods via the existing Helm chart in `deploy/chart/`. The UI pod has an OpenShift Route for external access; the BFF is cluster-internal only.

```
deploy/chart/values.yaml    # ui: and bff: pod entries
deploy/pods/Containerfile.bff  # UBI9 + Python 3.12 + FastAPI
```

All pods (ingestion, llm-analysis, assembly, delivery, bff, ui) are managed by the same Helm release:

```bash
helm upgrade --install cpg-ingester deploy/chart/ \
  --namespace $NAMESPACE \
  --set image.namespace=$NAMESPACE
```

### Docker Compose

Both services are in the root `compose.yml` under the `ingester-pods` profile:

```bash
podman-compose --profile ingester-pods up cpg-ingester-bff cpg-ingester-ui
```

| Service | Port | Notes |
|---|---|---|
| `cpg-ingester-bff` | 8095 | FastAPI, mock mode by default |
| `cpg-ingester-ui` | 3003 | nginx serving SPA, proxies `/api/` to BFF |

## Data

- `data/synthetic-hypertension-cpg.pdf` — Synthetic CPG for testing
- `data/golden/` — Golden DMN files for validation
