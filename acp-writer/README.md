# Actionable Care Plan Writer

Composes patient-specific, FHIR-compliant care plans by combining clinical decision logic (DMN), retrieved recommendations (vector store), and patient data (FHIR IPS). Uses a multi-agent LangGraph pipeline with adversarial review.

## Architecture

Two-phase LangGraph pipeline:

**Phase 1 — Clinical Reasoning:**
1. **Condition Scanner** — Extract patient conditions, medications, allergies from IPS (deterministic)
2. **Guideline Resolver** — Match conditions to registered CPGs and DMN models
3. **DMN Executor** — Evaluate decision models with concept-resolution pipeline for patient data extraction (see [Clinical Data QA](../docs/clinical-data-qa.md)). Uses an LLM (via MaaS/LiteLLM) as the final resolution fallback for open-vocabulary clinical terms; degrades gracefully to deterministic-only extraction when the LLM is unavailable
4. **Recommendation Retriever** — Search vector store for applicable recommendations
5. **Plan Composer** — LLM maps decisions + recommendations → Planning Brief
6. **Brief Reviewer** — Adversarial LLM review (clinical pharmacist persona, max 2 loops)

**Phase 2 — FHIR Generation:**
7. **FHIR Bundle Generator** — Deterministic FHIR R4 from Planning Brief (no LLM)
8. **Terminology Validator** — Verify all codes against SNOMED/RxNorm/LOINC/ICD-10
9. **FHIR Syntax Validator** — Structural validation + AI Transparency IG compliance
10. **FHIR Semantic Reviewer** — LLM review for clinical coherence (max 2 loops)
11. **FHIR Server Writer** — POST to HAPI FHIR + approve/reject workflow

### Sub-components

- **`decision-service/`** — Java/Quarkus (Apache KIE / Kogito) DMN engine runtime
- **`src/acp_writer/`** — Python pipeline service

Both the decision engine and vector store are internal implementation details, hidden behind the API.

## Getting Started

```bash
cd acp-writer
python3 -m venv .venv && source .venv/bin/activate
pip install -e "../shared" -e ".[test]"
```

### Run the pipeline via CLI

Requires LiteLLM proxy running:

```bash
LITELLM_URL=http://localhost:4000 acp-writer ../mock-EHR/data/patient-bundle-medication.json
```

### Run tests

```bash
# Unit tests (no external services needed)
pytest tests/ -k "not integration and not network"

# With live terminology servers
pytest tests/ -k "not integration"

# Full E2E (requires LiteLLM)
LITELLM_URL=http://localhost:4000 pytest tests/test_e2e.py -v
```

## API Contract

REST API defined in [`api/openapi.yaml`](api/openapi.yaml). MCP tools in [`api/mcp-tools.json`](api/mcp-tools.json).

### Endpoints

| Group | Endpoints | Purpose |
|---|---|---|
| **Guidelines** | `/api/v1/guidelines` | Register, list, get, delete CPG metadata |
| **Decisions** | `/api/v1/decisions/models`, `.../evaluate/{id}` | Deploy, list, remove, evaluate DMN models |
| **Knowledge** | `/api/v1/knowledge/recommendations`, `.../search` | Ingest, list, search recommendations |
| **Care Plans** | `/api/v1/careplans`, `.../status` | Generate, retrieve, approve/reject care plans |
| **Health** | `/health`, `/health/ready`, `/api/v1/status` | Liveness, readiness, component status |

### MCP Tools

| Tool | Description |
|---|---|
| `deploy_decision_model` | Deploy DMN to the decision engine |
| `list_decision_models` | List deployed models |
| `evaluate_decision` | Evaluate a model with inputs |
| `register_guideline` | Register CPG metadata |
| `ingest_recommendation` | Ingest a single recommendation |
| `ingest_recommendation_batch` | Ingest a RecommendationBundle |
| `search_recommendations` | Search recommendations by similarity |
| `generate_careplan` | Generate a care plan from an IPS Bundle |

## AI Transparency

Every care plan bundle includes:
- **AIAST `meta.security`** on all generated resources
- **AI-Device** resource (AI Transparency IG profile)
- **AI-Provenance** with CPG derivation lineage
- **Per-activity Provenance** linking to source recommendations
- On approval: AIAST → CLINAST_AIRPT, clinician added as verifier

## Clinical Data Extraction

The DMN Executor extracts patient data from FHIR IPS bundles using a layered resolution strategy:

1. **Prior DMN results** — chained decision outputs
2. **DecisionVariable.codes** — terminology codes from DMN metadata (when cpg-ingester provides them)
3. **Concept resolver** — deterministic mapping of 60+ observation terms, 20+ conditions, drug classes, and computed values (age, BMI) to FHIR codes
4. **KNOWN_VARIABLE_MAP** — legacy 6-entry hardcoded fallback

Temporal queries (time-windowed counts, consecutive readings, rate of change) are handled by named primitives in `tools/temporal_queries.py`.

See [Clinical Data QA](../docs/clinical-data-qa.md) for the full architecture.

### Benchmarking

```bash
# 50-question smoke suite
python -m acp_writer.benchmark run --suite smoke --backend current --no-mlflow

# 200-question standard suite
python -m acp_writer.benchmark run --suite standard --backend current --no-mlflow
```

See `benchmarks/README.md` for details.

## Observability

MLflow tracing via `mlflow.langchain.autolog()` + `mlflow.fastapi.autolog()`. Set `MLFLOW_TRACKING_URI` to enable.

## Cluster Deployment

See [`deploy/README.md`](../deploy/README.md) for the full cluster deployment guide.

### Quick reference

```bash
# Full deploy (builds + Helm + OpenShell sandboxes)
acp-writer/deploy/deploy.sh --config deploy/config/cluster.env

# Redeploy without rebuilding images
acp-writer/deploy/deploy.sh --skip-build --tag <sha> --config deploy/config/cluster.env

# Deploy with Helm-managed pods instead of OpenShell sandboxes
acp-writer/deploy/deploy.sh --skip-openshell --config deploy/config/cluster.env

# Verify
acp-writer/deploy/verify.sh --config deploy/config/cluster.env

# Teardown (preserves Secrets and ImageStreams)
acp-writer/deploy/teardown.sh --config deploy/config/cluster.env
```

### Pod-split architecture

In cluster mode (`openshellMode: true`), acp-writer runs as 5 OpenShell sandboxes + 1 Helm pod:

| Sandbox/Pod | Service | Role |
|---|---|---|
| `sb-patient-data` | `acp-patient-data` | IPS scanning, condition extraction |
| `sb-llm-reasoning` | `acp-llm-reasoning` | DMN input resolution, composition, recommendations |
| `sb-decision-engine` | `acp-decision-engine` | DMN evaluation (thin wrapper) |
| `sb-fhir-generation` | `acp-fhir-generation` | FHIR bundle generation |
| `sb-fhir-server` | `acp-fhir-server` | Care plan storage, FHIR write |
| `acp-ui` (Helm) | `acp-ui` | Web UI |

The Kogito decision service (`cpg-decision-svc-decision-service`) runs as a separate Helm deployment.

### SonataFlow workflow

The `acpwriter` SonataFlow workflow orchestrates the pipeline: ScanPatient → ResolveGuidelines → ExecuteDMN → RetrieveRecommendations → ComposePlan → GenerateBundle → ReviewFHIR → WritePlan. The workflow and its props CM (`acpwriter-props.yaml`) are applied automatically by `deploy.sh`.

## Decision Service (Internal)

Kogito auto-generates REST endpoints from DMN. Internal — use the acp-writer API, not Kogito directly.
