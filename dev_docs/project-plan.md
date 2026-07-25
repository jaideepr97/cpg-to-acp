# CPG-to-ACP Project Plan

> **Note:** This plan is directional. Phases, priorities, and technology choices are subject to change as the project evolves and as the Red Hat AI platform matures. Phase ordering beyond Phase 3 may be adjusted based on priorities and dependencies.

## Goal

Transform Clinical Practice Guidelines into patient-specific, FHIR-compliant, actionable care plans — running on OpenShift with Red Hat AI platform capabilities. Enable parallel development across areas with cross-cutting milestones.

## Current State (Phase 3.3 Complete)

Both cpg-ingester and acp-writer are multi-agent LangGraph pipelines with adversarial review, running on OpenShift with OpenShell sandboxing, SonataFlow orchestration, and MaaS inference. Phase 3.3 closed 2026-07-25 with a clean E2E test passing. Remaining items (multi-CPG E2E, FHIR approval lifecycle, golden test suite) captured in the backlog for future work.

**What works (verified in clean E2E on 2026-07-25):**
- **Full cross-pipeline E2E:** CPG PDF → cpg-ingester (Parse → LLM Analysis → Assembly → Delivery) → acp-writer (Scan → Resolve → Execute DMN → Retrieve Recs → Compose → Generate FHIR → Review → Write) → CarePlan on FHIR server
- **cpg-ingester:** Multi-agent LangGraph pipeline producing 5-9 DMN models + 12 recommendations from the synthetic hypertension CPG. Reviewer prompts tuned with CRITICAL/MINOR severity classification.
- **acp-writer:** 11-node pipeline producing care plans with clinically appropriate content (Lisinopril 10mg, BMP monitoring, BP confirmation). AI Transparency IG compliance. Approval workflow.
- **Infrastructure:** Pod-per-security-profile (11 pods), SonataFlow orchestration with async callbacks, MinIO artifact store with PHI-segmented buckets, API gateway, MCP Gateway (12 tools, 3 virtual servers), OpenShell sandboxes with per-pod network policies (Landlock + OPA + OCSF audit), MaaS inference (gpt-5.6-terra), MLflow tracing.

**Deferred to backlog:**
- Multi-CPG test with second CPG (diabetes — synthetic CPG prepared but not tested E2E on OpenShift)
- FHIR approval workflow E2E test (draft → active / entered-in-error)
- Golden test suite

**What doesn't exist yet:** Production UIs (current are minimal Python/Jinja), BPMN output, automation service, identity/auth, multi-CPG at scale.

---

## Phases

### Phase 2 — OpenShift + OpenShell + Platform Foundation (complete)

**Goal:** Get the system running on OpenShift with OpenShell sandboxing and governed inference.

OpenShell can sandbox the existing services without requiring a full multi-agent architecture. Deploying the current acp-writer + decision-service in an OpenShell sandbox on OpenShift establishes the governance pattern early.

#### Work Items

| Area | Work | Technology |
|---|---|---|
| **platform** | Deploy all services to OpenShift (Helm/Kustomize per component) | OpenShift |
| **platform** | Replace LiteLLM with MaaS for inference routing | MaaS |
| **platform** | Wrap acp-writer in OpenShell sandbox with per-binary network policies | OpenShell |
| **platform** | Add MLflow tracing across the pipeline | MLflow |
| **platform** | **Spike:** Agent framework evaluation — compare LangGraph, CrewAI, Rookery, and other options for multi-agent orchestration within cpg-ingester and acp-writer. Must align with OpenShell. | — |
| **platform** | **Spike:** Investigate Praxis as future inference gateway | — |
| **cpg-ingester** | Transition from synthetic to real CPG (VA/DoD guideline) | Docling |
| **cpg-ingester** | Enhance Docling usage: capture diagrams, images, multi-column layouts | Docling |
| **acp-writer** | Implement MCP tool interfaces for FHIR and DMN access | MCP |
| **shared** | Add MCP tool contracts to shared/ | — |
| **mock-EHR** | Verify IPS ($summary) support on HAPI FHIR | — |

#### Exit Criteria

- Pipeline runs on OpenShift
- acp-writer runs inside OpenShell sandbox with visible policy enforcement
- All inference routed through MaaS
- MLflow traces for every pipeline step
- Agent framework decision made (spike complete)
- At least one real CPG processed end-to-end

---

### Phase 3 — Multi-Agent + Knowledge + Minimal UI

**Goal:** Build the multi-agent architecture for both cpg-ingester and acp-writer. Add the recommendation/vector store pipeline. Introduce minimal UIs for upload and approval workflows.

Care plans in this phase include narrative activities based on process/recommendations from the CPG. BPMN generation is deferred to Phase 4.

Phase 3 is split into sub-phases that can advance independently. Phase 3.0 establishes the shared contracts that both sides depend on. After that, Phase 3.1 (cpg-ingester) and Phase 3.2 (acp-writer) can proceed in parallel — neither blocks the other.

---

#### Phase 3.0 — Contracts and Shared Infrastructure (complete)

**Goal:** Define the recommendation contract (the last undefined boundary between cpg-ingester and acp-writer) and establish cross-cutting infrastructure so the two tracks can work independently.

| Area | Work | Notes |
|---|---|---|
| **shared** | Define recommendation contract in `shared/` — Pydantic models for recommendations pushed from cpg-ingester to acp-writer | `cpg_contracts.recommendations`: `Recommendation`, `RecommendationBundle`, `CertaintyGrade`, `CrossReference`, 6 validated enums. Contract version 1.0. See `dev_docs/design/contract-proposal-ingester-writer.md`. |
| **shared** | Define CPG metadata contract — guideline-level information | `cpg_contracts.guidelines`: `CPGMetadata`, `GradingSystem`. Registered once per CPG; all artifacts reference by `cpg_id`. |
| **shared** | Define knowledge ingestion API contract — the REST/MCP interface acp-writer exposes for receiving recommendations | OpenAPI v0.2.0: guidelines CRUD, recommendation ingestion (single + batch), search with type/strength filters. MCP tools updated. |
| **shared** | Refine decision model contract | `DecisionCategory` enum, `description`/`codes` on variables, `modifies` list for subpopulation overrides. |
| **research** | CPG structural analysis | Analyzed 42 CPGs from 7 organizations. See `dev_docs/design/cpg-analysis.md`. |

##### Exit Criteria

- [x] Recommendation contract defined in `shared/` with Pydantic models
- [x] Knowledge ingestion API contract defined (OpenAPI + MCP tool schema)
- [x] Both cpg-ingester and acp-writer teams can implement against the contract independently
- [x] Test fixtures available for both tracks (`shared/tests/fixtures/sample-recommendations.json`)

---

#### Phase 3.1 — cpg-ingester Multi-Agent Pipeline (complete)

**Goal:** Replace the single-prompt DMN extraction with a multi-agent pipeline that extracts both DMN decision tables and narrative recommendations from CPGs.

Can proceed independently after Phase 3.0 contracts are defined. Does not depend on acp-writer's vector store being operational — cpg-ingester outputs recommendations in the contract format and pushes them via the API. If acp-writer's knowledge endpoint isn't ready, cpg-ingester can validate output against the contract schema without a live endpoint.

| Work | Notes |
|---|---|
| Wire agents together using LangGraph (StateGraph) | Framework selected in Phase 2 spike |
| Add filtering agent — identifies relevant vs. irrelevant CPG sections | First node in the graph |
| Add decision identification agent — classifies content as decisions vs. process/recommendations | Splits the pipeline into two tracks |
| Add DMN writing agent — produces high-quality DMN with validation | Replaces single-prompt extraction; validates against golden test cases |
| Add recommendation extraction agent — extracts process/recommendations in the shared contract format | Outputs recommendation contract objects |
| Add push step — sends DMN and recommendations to acp-writer via API/MCP | Extends existing `cpg-deploy-dmn` to also push recommendations |
| Create mock acp-writer receiver — captures DMN and recommendation artifacts to files for review | Lightweight stub that implements the contract API and writes received artifacts to a local directory. Enables testing cpg-ingester end-to-end without a running acp-writer. |
| Incorporate AutoRAG for retrieval optimization (if it makes sense) | AutoRAG |
| Minimal UI: upload CPG (PDF), review/approve extracted decisions and recommendations | Simple workflow: upload → review → approve → push to acp-writer |

##### Exit Criteria

- cpg-ingester is a multi-agent pipeline (LangGraph StateGraph with 4+ nodes)
- Produces both DMN and recommendations in the shared contract format
- DMN validated against golden test cases
- Recommendations validated against the shared contract schema
- Minimal upload/review UI functional
- All agents traced in MLflow

---

#### Phase 3.2 — acp-writer Multi-Agent Composition (complete)

**Goal:** Replace the hardcoded care plan composition with a multi-agent system that uses DMN decisions, retrieved recommendations, and FHIR expertise to produce clinically complete care plans.

**Design:** `dev_docs/design/acp-writer-design.md` | **Plan:** `working/phase3.2-implementation.md`

| Work | Status |
|---|---|
| **Spike:** Vector store selection (pgvector) | ✅ |
| Project scaffolding + dependencies | ✅ |
| Guidelines CRUD + recommendation ingestion + vector store | ✅ |
| Planning Brief Pydantic schema | ✅ |
| State schema + LangGraph pipeline skeleton (11 nodes) | ✅ |
| Condition Scanner (deterministic FHIR traversal) | ✅ |
| Guideline Resolver (condition → CPG scope matching) | ✅ |
| Terminology lookup tool (SNOMED/RxNorm/LOINC/ICD-10) | ✅ |
| IPS targeted extraction tool | ✅ |
| DMN Executor (topological order, targeted extraction) | ✅ |
| Recommendation Retriever (vector search) | ✅ |
| Plan Composer (LLM → PlanningBrief) | ✅ |
| Brief Reviewer (adversarial, clinical pharmacist) | ✅ |
| FHIR Bundle Generator (deterministic, AI Transparency IG) | ✅ |
| Terminology + FHIR Syntax Validators | ✅ |
| FHIR Semantic Reviewer (adversarial LLM) | ✅ |
| FHIR Server Writer + approval workflow (AIAST → CLINAST_AIRPT) | ✅ |
| E2E integration tests + legacy removal + README | ✅ |
| Minimal UI: review and approve a generated care plan | ✅ |

##### Exit Criteria

- [x] acp-writer produces CarePlans with recommendation-backed narrative activities
- [x] Vector store operational with recommendation retrieval
- [x] Knowledge ingestion and guidelines CRUD endpoints functional
- [x] Care plan composition uses both DMN decisions and retrieved recommendations
- [x] Planning Brief validated by adversarial reviewer before FHIR generation
- [x] FHIR output passes terminology, syntax, and semantic validation
- [x] AI Transparency on FHIR IG compliant (AIAST tags, AI-Device, AI-Provenance)
- [x] Care plans written to HAPI FHIR server
- [x] Approval workflow changes AIAST → CLINAST_AIRPT
- [x] Minimal review/approval UI functional
- [x] All agents traced in MLflow

---

#### Phase 3.3 — Integration, Governance, and End-to-End Testing (complete)

**Goal:** Connect cpg-ingester and acp-writer end-to-end, apply governance (OpenShell, MCP Gateway), split into pod-per-security-profile with workflow orchestration, and validate the complete pipeline with multiple CPGs.

Requires Phase 3.1 and Phase 3.2 to be substantially complete. This is where the independently-developed tracks are integrated and hardened.

##### Pre-work (fixes and improvements before integration)

| Area | Work | Notes |
|---|---|---|
| **acp-writer** | FHIR bundle & server workflow | Combined: fix reject status ("revoked" → "entered-in-error"), add Patient to transaction bundle with conditional create, implement full server-side lifecycle (draft on creation, active on approve, entered-in-error on reject). |
| **acp-writer** | Fix Provenance targetPath for inline activities | Use AI Transparency on FHIR IG `targetPath` extension to target specific fields within a resource, instead of referencing non-existent standalone resources. Eliminates unresolved reference warnings. |
| **acp-writer** | Improve reviewer iterations and prompts | Max iterations 2 → 4. Reviewer should APPROVE when good enough (stop nitpicking). Strengthen Plan Composer prompt to get it right first attempt. |
| **acp-writer** | Parallelize Phase 2 validators | Terminology Validator ∥ FHIR Syntax Validator (both deterministic, independent; fan-in before FHIR Semantic Reviewer). Note: DMN Executor → Recommendation Retriever must remain sequential (Retriever uses DMN outputs to enrich vector search). |
| **acp-writer** | SqliteSaver for persistent checkpointing | Replace MemorySaver so pipeline state survives restarts and historical runs are visible in UI. |

##### Phase 3.3 work items

| Area | Work | Notes |
|---|---|---|
| **spike** | **Spike: SonataFlow for pod-split pipeline orchestration** | SonataFlow selected (Apache KIE, same ecosystem as Kogito). Spike focuses on how to use it: deploy operator, implement review-loop pattern in Serverless Workflow DSL, state transfer between pods, CloudEvents vs REST, RHDH Orchestrator supported path, MLflow trace propagation. Prototype acp-writer Phase 1 pipeline as a SonataFlow workflow. Pod groups with a single node (e.g., DMN Executor) should be plain REST services. |
| **spike** | **Spike: MCP Gateway for governed tool access** | Research what MCP Gateway provides and how it fits this project. MCP Gateway is a major Red Hat AI offering — valuable to demonstrate. Determine: which tools to govern, what policies to apply (rate limiting, agent-level access control, audit logging), and how it integrates with OpenShell. |
| **integration** | End-to-end test: cpg-ingester → acp-writer live | cpg-ingester pushes DMN + recommendations via Delivery Agent → acp-writer generates care plans. Verify Delivery Agent works against the new guidelines/recommendations/batch endpoints. Verify contract compatibility, data flow, error handling. |
| **integration** | Validate recommendation indexing and retrieval | Recommendations produced by cpg-ingester are correctly embedded, indexed, and retrieved by acp-writer's vector store |
| **integration** | Test with the synthetic CPG end-to-end on OpenShift | Full pipeline on-cluster |
| **integration** | Add a second CPG for multi-CPG testing | Prepare or find a second CPG with overlapping scope. Pipeline should handle multiple CPGs producing a single care plan with duplicates and conflicts present (conflict resolution is deferred — just let them through). |
| **cpg-ingester** | Split cpg-ingester into pod-per-security-profile with orchestrator * | OpenShell fine-grained sandboxing. See `dev_docs/design/cpg-ingester-design.md` § Deployment Model |
| **acp-writer** | Split acp-writer into pod-per-security-profile with orchestrator * | OpenShell fine-grained sandboxing. See `dev_docs/design/acp-writer-design.md` § Deployment Model |
| **platform** | OpenShell policies per agent (network, filesystem, credential scoping) | Requires pod split — policies are per-pod, not per-function within a pod |
| **platform** | MCP Gateway integration | Based on spike findings. Demonstrate governed tool access as a Red Hat AI capability. |
| **testing** | Golden test cases for the full pipeline (CPG → DMN + recommendations → CarePlan) | Regression suite for future phases. Include both single-CPG and multi-CPG scenarios. |

\* Pod split requires an orchestration engine (spike above) to coordinate work across pods. Each pod group registers as a service; the orchestrator drives the pipeline. UIs run in their own pods (separate from agent backends, enables independent evolution). The in-process LangGraph pipeline remains as the within-pod execution model for pod groups with multiple nodes; pod groups with a single node (e.g., DMN Executor) should be plain REST services. The orchestrator handles the between-pod coordination. Total: 5 cpg-ingester pods + 6 acp-writer pods = 11 pod groups.

##### Conflict resolution — deferred

Full conflict resolution (interactive clinician UI, structured conflict types, resolution tracking in Provenance) is deferred beyond Phase 3.3. Multi-CPG testing in this phase will surface duplicates and conflicts in the care plan, but they will not be resolved automatically — the clinician sees them and can reject the plan if needed.

##### Exit Criteria

- [x] End-to-end pipeline: cpg-ingester → acp-writer produces CarePlans using both DMN and recommendations — **PASS** (2026-07-25: CarePlan/1115 with 4 goals + 4 activities, clean re-run with zero intervention)
- [ ] Pipeline tested with at least two CPGs — **NOT MET** (synthetic diabetes CPG prepared but not tested E2E on OpenShift)
- [x] Pipeline runs on OpenShift with MLflow traces visible for every step — **PASS**
- [x] Both cpg-ingester and acp-writer split into pod-per-security-profile — **PASS** (11 pods)
- [x] Orchestration engine selected and driving cross-pod pipeline execution — **PASS** (SonataFlow with async callbacks)
- [x] OpenShell agent policies applied and enforced per pod — **PASS** (9 sandboxes with Landlock + OPA + OCSF, unauthorized endpoints blocked)
- [x] MCP Gateway demonstrating governed tool access — **PASS** (12 tools, 3 virtual servers)
- [ ] FHIR server integration working (draft → active / entered-in-error) — **PARTIAL** (draft write works, approval lifecycle not tested E2E through SonataFlow)
- [x] Pipeline parallelism: Terminology Validator ∥ FHIR Syntax Validator — **PASS** (LangGraph fan-out/fan-in implemented)
- [x] Inference routed through MaaS on OpenShift — **PASS** (gpt-5.6-terra via MaaS gateway)
- Golden test cases passing
- All Phase 3.1 and Phase 3.2 exit criteria met

---

### Phase 4 — UI + UX + Demo-Ready

**Goal:** Replace the minimal Python/Jinja UIs with production-quality React/PatternFly applications. Make the system demo-ready with a mock-EHR that launches the acp-writer via SMART on FHIR.

> **Re-prioritized:** UI work was moved from Phase 7 to Phase 4. After Phase 3.3, the backend is functionally complete (CPG → care plan → FHIR server with governance), but invisible without proper UIs. Demo readiness is the highest priority. See `working/prompts/planning_260722_analysis.md` for the full analysis.

> **Important:** The UI must never display the Red Hat logo or name. PatternFly supports white-labeling.

#### Spikes

| Spike | Focus | Status | Results |
|---|---|---|---|
| **A. UI Technology & Design System** | PatternFly 6 + React + TypeScript, PatternFly AI components, build tooling | ✅ Complete | [`dev_docs/ui/spike-a-technology.md`](ui/spike-a-technology.md) |
| **B. UI ↔ Backend Interaction Pattern** | Async communication, WebSocket vs SSE vs polling, BFF pattern, human-in-the-loop | ✅ Complete | [`dev_docs/ui/spike-b-backend-interaction.md`](ui/spike-b-backend-interaction.md) |
| **C. cpg-ingester UX Design** | Upload flow, CPG lineage, item manifest review, DMN visualization, approval workflow | ✅ Complete | [`dev_docs/ui/spike-c-cpg-ingester-ux.md`](ui/spike-c-cpg-ingester-ux.md) |
| **D. acp-writer UX Design** | Patient context, care plan visualization, multi-CPG conflicts, AI Transparency, approval | ✅ Complete | [`dev_docs/ui/spike-d-acp-writer-ux.md`](ui/spike-d-acp-writer-ux.md) |
| **E. mock-EHR Research** | Medplum vs HAPI+components vs custom, SMART on FHIR, SMART-EHR-Launcher evaluation | ✅ Complete | [`dev_docs/ui/spike-e-mock-ehr.md`](ui/spike-e-mock-ehr.md) |

#### Work Items (staged)

| Stage | Area | Work | Auth needed? |
|---|---|---|---|
| 4.0 | **research** | ~~Complete Spikes A-E~~ ✅ Complete | No |
| 4.1 | **cpg-ingester** | Rebuild cpg-ingester UI in React/PatternFly — upload, review, approve flow. Show CPG-to-recommendation lineage. | No |
| 4.2 | **mock-EHR** | Evaluate and set up mock-EHR (Medplum vs HAPI+components vs custom). Patient list, basic EHR UI. | No |
| 4.3 | **acp-writer** | Rebuild acp-writer UI in React/PatternFly — care plan review, FHIR Bundle visualization, approve/reject. Standalone initially (mock patient context). | No |
| 4.4 | **platform** | Lightweight SMART on FHIR auth — Medplum built-in OAuth, Keycloak minimal (single realm, one user), or mock OAuth stub. Just enough for the launch flow. | Minimal |
| 4.5 | **integration** | Connect acp-writer UI to mock-EHR via SMART on FHIR launch. Clinician clicks patient → acp-writer launches in context → care plan generated. | Minimal |

#### Deferred to later phases

- Interactive editing of DMN (Phase 8 — needs DMN editor or chat interaction)
- Interactive editing of recommendations (Phase 8)
- Interactive editing of care plan activities (Phase 8)
- User-added clinical documentation for care plan context (Phase 8)
- Interactive conflict resolution (Phase 8 — needs structured conflict types)

#### Exit Criteria

- Both cpg-ingester and acp-writer have React/PatternFly UIs
- cpg-ingester UI shows CPG → decision/recommendation lineage
- acp-writer UI visualizes care plans and supports approve/reject
- mock-EHR launches acp-writer via SMART on FHIR with patient context
- UIs communicate with backend asynchronously (no blocking calls)
- Demo-ready: 5-minute walkthrough of full pipeline through the UIs

---

### Phase 5 — BPMN + Automation

**Goal:** Add BPMN generation to make care plans actionable. Connect acp-writer to the automation service.

#### Work Items

| Area | Work | Notes |
|---|---|---|
| **acp-writer** | Add BPMN writing agent — writes BPMN for process/recommendations | — |
| **acp-writer** | Include BPMN in DocumentReferences linked to CarePlan activities via extension | FHIR extension design |
| **acp-writer** | Publish BPMN to automation service on care plan approval | — |
| **automation** | Implement automation service that accepts BPMN from acp-writer | Receives BPMN over API |
| **shared** | Define the BPMN contract in shared/ | — |
| **acp-writer UI** | Add BPMN visualization within care plan review | BPMN renderer in React UI |

#### Exit Criteria

- acp-writer generates BPMN for automatable activities
- Automation service receives and stores BPMN
- BPMN visible in the care plan review UI

---

### Phase 6 — Governance + Safety + Evaluation

**Goal:** Quality gates, guardrails, and evaluation pipelines.

#### Work Items

| Area | Work | Technology |
|---|---|---|
| **platform** | NeMo Guardrails on agent I/O — healthcare-specific rules | NeMo Guardrails |
| **platform** | EvalHub — golden test sets per CPG, extraction fidelity scorers, plan quality scorers | EvalHub |
| **platform** | EvalHub gates that block deployment of degraded models/pipelines | EvalHub |
| **platform** | Garak red-teaming for healthcare-specific adversarial scenarios | Garak |
| **platform** | Migrate inference gateway to Praxis (if available) | Praxis |
| **platform** | **Evaluate:** Using smaller self-hosted models (via vLLM) instead of frontier models for cost and latency | vLLM |
| **cpg-ingester** | Validation pipeline: compare extracted DMN against golden test cases | — |
| **acp-writer** | Validate CarePlan output against AI Transparency on FHIR IG | — |
| **acp-writer** | CarePlan quality scoring (automated + clinician review) | — |

#### Exit Criteria

- Guardrails actively filtering agent I/O
- EvalHub gates preventing degraded deployments
- Three audit trails: MLflow (tracing), OpenShell (sandbox), automation (execution)
- AI Transparency on FHIR compliance
- Self-hosted model evaluation complete

---

### Phase 7 — Identity, Auth & Access Control

**Goal:** Establish full user authentication, role-based access control, and agent credential scoping. Replace the lightweight Phase 4 auth with production-grade identity infrastructure.

> **Note:** Phase 4 uses lightweight SMART on FHIR auth (Medplum built-in, Keycloak minimal, or mock stub) for demos. This phase adds production identity: RBAC, SPIFFE/SPIRE agent credentials, audit trails, and multi-user auth.

#### Work Items

| Area | Work | Technology |
|---|---|---|
| **platform** | Deploy Keycloak on OpenShift (full), configure OIDC provider | Keycloak |
| **platform** | Define roles (clinician, admin, reviewer) and map to permissions | Keycloak RBAC |
| **platform** | Agent identity via SPIFFE/SPIRE | SPIFFE/SPIRE |
| **platform** | OpenShell credential scoping — agents run with user-scoped tokens, not shared service accounts | OpenShell + Keycloak |
| **platform** | Audit trail linking actions to authenticated identities | MLflow + OpenShell |
| **acp-writer** | Integrate OIDC auth into UI and API (upgrade from Phase 4 lightweight auth) | — |
| **cpg-ingester** | Integrate OIDC auth into UI and API | — |
| **mock-EHR** | Configure HAPI FHIR for token-based access | — |

#### Exit Criteria

- Keycloak running on OpenShift with OIDC configured
- At least three roles (clinician, admin, reviewer) with distinct permissions
- Agent credentials scoped per-user via OpenShell + SPIFFE/SPIRE
- All UIs require authentication; APIs enforce token-based access
- Audit trail links every action to an authenticated identity

---

### Phase 8 — Scale + Polish

**Goal:** Multiple CPGs at scale, interactive editing, conflict resolution, and production polish.

#### Work Items

| Area | Work | Notes |
|---|---|---|
| **integration** | Expand to 3-5 real CPGs (VA/DoD) | — |
| **acp-writer** | Multi-plan merging when multiple CPGs apply | Conflict detection |
| **acp-writer** | Conflict resolution with clinician input | Interactive UI, structured types, Provenance tracking |
| **cpg-ingester UI** | Interactive DMN editing (chat-based or visual editor) | — |
| **cpg-ingester UI** | Interactive recommendation editing | — |
| **acp-writer UI** | Interactive care plan editing | — |
| **acp-writer UI** | User-added clinical documentation for care plan context | Free text input |
| **automation** | Add BPMN execution engine or BPMN-to-Ansible converter | Ansible/SonataFlow |

#### Exit Criteria

- 3-5 CPGs with multi-plan merging and conflict resolution
- Interactive editing in both UIs
- Production-ready

---

## Technology Adoption Timeline

| Phase | Status | Technologies Added |
|---|---|---|
| Phase 1 | Complete | Docling, LiteLLM (local), Drools/Kogito |
| Phase 2 | Complete | OpenShift, OpenShell, MaaS, MLflow, MCP |
| Phase 3.0 | Complete | cpg-contracts v1.0 (recommendations, guidelines, search) |
| Phase 3.1 | Complete | LangGraph (cpg-ingester agents) |
| Phase 3.2 | Complete | pgvector, LangGraph (acp-writer agents), AI Transparency IG |
| Phase 3.3 | In progress | MCP Gateway, SonataFlow, MinIO, async callbacks, API gateway, pod-per-security-profile |
| Phase 4 | Not started | React, PatternFly 6, TypeScript, SMART on FHIR (lightweight), Medplum (evaluate) |
| Phase 5 | Not started | — (BPMN generation, no new platform tech) |
| Phase 6 | Not started | NeMo Guardrails, EvalHub, Garak, vLLM, Praxis |
| Phase 7 | Not started | Keycloak (full), SPIFFE/SPIRE |
| Phase 8 | Not started | — (scale and polish, no new platform tech) |

## Parallel Development Tracks

Each area can advance semi-independently within a phase. Cross-cutting dependencies are noted in the phase tables. The key synchronization points are:

1. **Agent framework selection (Phase 2 spike)** — blocks all multi-agent work in Phase 3. Decision: LangGraph (see `dev_docs/spikes/spike-agent-framework.md`).
2. **OpenShift deployment (Phase 2)** — blocks OpenShell, MaaS
3. **Recommendation contract (Phase 3.0)** — blocks both Phase 3.1 and Phase 3.2. This is the single gate before cpg-ingester and acp-writer can advance independently.
4. **UI technology decision (Phase 4 Spike A)** — blocks all UI development in Phase 4.
5. **BPMN contract in shared/ (Phase 5)** — blocks automation service integration
6. **Keycloak full deployment (Phase 7)** — blocks production auth. Lightweight SMART on FHIR auth in Phase 4 does not require full Keycloak.

Within Phase 3, the cpg-ingester track (3.1) and acp-writer track (3.2) are designed to advance independently after the shared contracts (3.0) are defined. Neither blocks the other — cpg-ingester validates recommendations against the contract schema, acp-writer tests against hand-crafted recommendation data.

## Backlog — Phase-Independent Tasks

Work that can be picked up at any time, independent of the current phase. These items improve the project but don't block other work.

| Item                              | Status | Area         | Notes                                                                                                                                                                                                                                                                                                                           |
|-----------------------------------|---|--------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| MaaS with Vertex AI (Claude)      | Not started | platform     | Configure MaaS ExternalModel to route to Claude on Vertex AI. Requires a GCP service account key (not ADC user credentials) with the Vertex AI User role, and `oauth2` auth type on the ExternalProvider. OpenAI routing is already working; this adds Claude as a second provider option on-cluster.                           |
| Enhance tracing in MLflow         | Not started | all          | Make sure that the use of MLflow is optimized and that traces are useful.                                                                                                                                                                                                                                                       |
| FEEL expression validator         | Not started | cpg-ingester | Replace regex-based FEEL checks with a proper validator. Best option: expose a validation endpoint from the Kogito runtime (already running in acp-writer, Apache 2.0). No mature license-compatible Python FEEL parser exists.                                                                                                 |
| DMN validator                     | Not started | cpg-ingester | Improve the DMN validator, look for opensource solutions and potentially expose an endpoint from Kogito to test.                                                                                                                                                                                                                |
| Upgrade DMN to 1.5                | Not started | cpg-ingester | Currently targeting DMN 1.4 (latest supported by Drools/Kogito at conformance level 3). DMN 1.5 (Aug 2024) adds useful FEEL functions (`context put`, `now()`, `today()`). Upgrade when Drools/Kogito formally supports 1.5. Watch [Drools releases](https://github.com/apache/incubator-kie-drools/releases).                  |
| Abbreviation expansion in Rec Extractor | ✅ Complete | cpg-ingester | Rec Extractor prompt now expands ALL occurrences of abbreviations in `content` as "Full Name (ABBREVIATION)". No bare abbreviations — content is self-contained for vector search. |
| Provenance CPG lineage improvement | Not started | acp-writer | Per-activity Provenance currently only references recommendation ID. Should include CPG title, section, page numbers (from SourceLocation), and recommendation title for meaningful lineage display in the care plan bundle. |
| Improve conflict resolution in care plans | Not started | acp-writer | Current conflict handling is placeholder detection only. Needs interactive clinician resolution UI, structured conflict types (same target, contradictory, overlapping), resolution tracking in Provenance, multi-CPG conflict support. See design doc § Conflict Resolution. |
| FHIR transaction bundle patient reference | Phase 3.3 | acp-writer | Transaction bundle references Patient by ID but doesn't include the Patient resource. Normally the patient exists on the FHIR server (IPS originated from there), but need to handle the case where it doesn't — either include Patient in the transaction or use conditional references. |
| Approval workflow should POST/update on FHIR server | Phase 3.3 | acp-writer | Care plan should be POSTed to FHIR in "draft" status on creation. Approval updates status to "active" on the FHIR server; rejection updates to "entered-in-error". AIAST → CLINAST_AIRPT transition should be reflected on the server, not just in-memory. |
| FHIR server-side validation ($validate) | Not started | acp-writer | Use HAPI FHIR's $validate operation to validate generated Bundles before writing. Currently only client-side validation. |
| Embedding model tuning for clinical domain | Not started | acp-writer | Current vector store uses FakeEmbeddingProvider. Evaluate clinical-domain embedding models (NeuML/pubmedbert-base-embeddings or similar) for recommendation retrieval quality. |
| PatientSummary allergies field | Not started | acp-writer | The PatientSummary Pydantic model doesn't include allergies. Add AllergyIntolerance extraction from IPS Bundle. |
| Rename technology-specific variables | Not started | all | Variables like LITELLM_URL, litellm_url should use role-based names (LLM_BASE_URL, INFERENCE_URL). Technology names create confusion during provider transitions (LiteLLM → MaaS). |
| Transition from LiteLLM to MaaS | Not started | platform | Phase 2 deployed LiteLLM on-cluster as the inference proxy. MaaS gateway is now operational but LiteLLM references remain in code and config. Complete the transition. |
| MinIO IAM policies for PHI bucket access | Not started | platform | Currently all pods share one MinIO credential. Add per-pod IAM policies so pods only access the buckets they need (cpg-artifacts vs cpg-phi). |
| cpg-ingester: images/charts/diagrams | Not started | cpg-ingester | Extract and interpret visual content from CPGs (treatment algorithm flowcharts, dosing charts, diagrams). Requires a vision model — Docling detects image regions but doesn't interpret content. |
| cpg-ingester: OCR for scanned PDFs | Not started | cpg-ingester | Add tesseract or EasyOCR support for scanned PDF pages. Docling's text extraction works for digital-native PDFs but older/scanned guidelines need OCR. |
| Review `_extract_section_text` robustness | Not started | cpg-ingester | Current implementation in `generation.py` uses heading-level matching to extract section text. It now skips non-numbered headings (e.g., "Decision Table 1:", "Key principles:") but may still be brittle for CPGs with inconsistent heading structures, deeply nested sections, or non-standard numbering. Consider using the section_map page ranges as a fallback or combining heading-based and page-based extraction. |
| SonataFlow callback timeouts and retry | Not started | automation | Async callback states (Parse, Analyze in cpg-ingester; ComposePlan, GenerateBundle, ReviewFHIR in acp-writer) hang forever if the service pod dies mid-work. Add `timeouts.eventTimeout` to each callback state so SonataFlow transitions to an error/retry path instead. Design the retry flow: re-trigger the async call with the same MinIO ref, track attempt count, escalate after N failures. |
| Parallel DMN and rec extraction | Not started | cpg-ingester | `generate_all()` runs DMN generation sequentially before rec extraction, but they're independent (different manifest items, no shared output). Run them as parallel LangGraph branches to roughly halve LLM analysis time. Constraint: MaaS rate limits may need tuning for doubled concurrent calls. |
| DMN model discovery in pod-split deployment | Not started | acp-writer | In the monolith, `_dynamic_models` in `api.py` tracks deployed DMN models in-memory. In the pod-split deployment, DMN XML is delivered to the decision-engine pod but the guideline resolver in the llm-reasoning pod cannot discover them — `applicable_dmn_models` is always empty. Fix: either have the decision-engine pod expose a model listing endpoint that the guideline resolver queries, or store deployed model summaries in MinIO/a shared registry so both pods can see them. |
| In-memory state lost on pod restart | Not started | acp-writer | Guidelines and recommendations are stored in-memory (`_guidelines_store`, `_vector_store`). Pod restarts lose all registered CPGs and ingested recommendations, requiring re-delivery from cpg-ingester. Fix: persist to MinIO or a database, or reload from MinIO on startup. |
| Review SonataFlow inline vs ref data flow | Not started | acp-writer | Several acp-writer service endpoints pass intermediate data (condition_codes, dmn_results, applicable_cpgs, patient_demographics, medication_codes) inline through SonataFlow workflow state rather than via MinIO refs. Review: (1) which fields could exceed SonataFlow payload limits as CPG complexity grows, (2) whether resolve_ref should be added to `/resolve` and `/retrieve` endpoints, (3) the general pattern of how data flows between SonataFlow states and whether large payloads should always use ref-based transfer. Currently safe for the hypertension CPG (~8 DMN models, handful of conditions) but may break with larger CPGs or multi-CPG scenarios. |
| OpenShell transparent service routing | Not started | deploy | Current integration uses an nginx hostname-translation router to bridge K8s services → OpenShell gateway. Future: OpenShell mutating webhook or supervisor init container injection for transparent pod integration. See `dev_docs/design/openshell-integration-findings.md`. |
| OpenShell botocore proxy compatibility | Not started | deploy | boto3 S3 PUT fails through OpenShell CONNECT proxy (response not relayed). Workaround: presigned URL + requests. File upstream issue with OpenShell. See `dev_docs/design/openshell-integration-findings.md`. |
| OpenShell short hostname matching | Not started | deploy | OPA engine requires exact hostname match — short K8s DNS names don't match FQDN wildcards. Currently duplicating entries. Request upstream support for DNS-aware matching. |
| Multi-CPG E2E test on OpenShift | Phase 3.3 | acp-writer | Synthetic diabetes CPG (`SYN-DM2-2026-001`) prepared and tested in local integration (24/24 checks pass). Not yet tested E2E on OpenShift through SonataFlow with OpenShell sandboxing. Need to verify multi-CPG care plan generation with overlapping scope (hypertension + diabetes → combined care plan with potential duplicates). |
| FHIR approval lifecycle E2E test | Phase 3.3 | acp-writer | Care plans are written as `draft`. The approve/reject flow (draft → active / entered-in-error) exists in code and works locally but has not been tested end-to-end through SonataFlow on OpenShift. May need a separate SonataFlow workflow or a manual trigger endpoint. |
| Golden test suite | Phase 3.3 | testing | Comprehensive regression suite for the full pipeline: single-CPG medication, single-CPG lifestyle, multi-CPG diabetes+hypertension, no-guidelines. Parameterized tests verifying structural patterns (not exact text). Gate behind inference endpoint. See `working/phase3.3-implementation.md` Step 15. |
| E2E test automation script | Phase 3.3 | testing | Update `scripts/run-e2e-openshift.sh` with SonataFlow-based pipeline execution, OpenShell sandbox deployment, and results verification. Current E2E is manual CLI commands. |
| cpg-ingester metadata extractor null handling | ✅ Complete | cpg-ingester | `raw.get("title", "Untitled")` returns None when LLM outputs explicit null. Fixed to use `or "Untitled"` pattern. Commit `40ebd7d`. |
| acp-writer workflow ips_ref fix | ✅ Complete | acp-writer | SonataFlow workflow passed `ips_bundle` (null inline) instead of `ips_ref` (MinIO reference) to scan endpoint. Fixed in commit `9d80206`. |
| acp-writer patient-data scan ref resolution | ✅ Complete | acp-writer | Scan endpoint now resolves IPS from MinIO ref (`ips_ref`) in addition to inline `ips_bundle`. Uses `resolve_ref()` + fallback for legacy key name. Commit `b8cbaf0`. |
| Preserve ingester-assigned GUIDs (identity contract) | Not started | shared / cpg-ingester / acp-writer | Contract-proposal design decision #2 requires ingester-assigned GUIDs to be preserved end-to-end, but they are lost on both sides. cpg-ingester never emits a `DecisionModelSummary` (`dmn_creator.py` returns only `dmn_xml`; `generation.py:221` reads an always-empty summary), so the manifest GUID, `category`, `modifies`, and `source_location` for decisions never cross the boundary. acp-writer then re-derives the id from the model name (`api.py:91`, `decision_engine.py:37`), ignoring `root.get("id")`. Net effect: `CrossReference.target_id` GUIDs to decision models can't resolve, `modifies` override chains break, same-named models collide. Fix: emit `DecisionModelSummary` (carrying the manifest id) from the DMN track and deliver it; have acp-writer read and preserve the DMN root `id` instead of deriving from the name. |
| Clinical review gates fail open and don't gate the server write | Not started | acp-writer | Three related gaps let unvalidated/unreviewed bundles reach the FHIR server. (1) `brief_reviewer.py:109` and `fhir_semantic_reviewer.py:70` treat any reviewer-response parse error as `APPROVE` — a clinical gate should fail closed or flag, not silently approve. (2) The FHIR semantic-review loop is inert: `fhir_bundle_generator.py:26` reads `fhir_review_feedback` but never applies it, so a REVISE verdict regenerates a byte-identical bundle until the counter exhausts. (3) `syntax_errors`/`terminology_issues` never block `fhir_server_writer.py`. Make deterministic validation gate the write, and make the review loop actually consume feedback. |
| Enforce terminology API verification during composition | Not started | acp-writer | Design decision #4 / Node 5 require every FHIR code to be API-verified ("never trust the LLM's memory"). `plan_composer.py` never calls `tools/terminology_lookup` — it accepts LLM-emitted codes verbatim. The Terminology Validator only records `terminology_issues`; it never fixes codes or writes the promised `CarePlan.note` "Code verification gap" entries, and nothing downstream consumes the list. Wire terminology lookup into the Plan Composer and have the validator repair/flag unresolvable codes. |
| Validate `contract_version` on ingestion | Not started | acp-writer | Contract principle #6 / design decision #6 require acp-writer to validate `contract_version` and reject incompatible payloads. There are no references to `contract_version` in `acp-writer/src`; `register_guideline` (`api.py:311`) and `ingest_recommendation_batch` (`api.py:355`) accept any/absent version. Add a version check on the ingest endpoints. |
| Escalated items are dropped, never surfaced | Not started | cpg-ingester | `generation.py:217,245` append results only when `not result.get("escalated")`, and the escalation flag set in subgraph state is never written back to the manifest. Assembly looks for `item.get("escalated")` on manifest items (`assembly.py:115`) — a flag never set there — so `escalated-items.json` is always empty and escalated clinical content is neither delivered nor reviewed (violates design principle #9). Fix: propagate escalation back to the manifest/report and include escalated items in the human-review output. |
| Assembly disk-fallback can deliver unvalidated DMN | Not started | cpg-ingester | `dmn_creator.py:90` writes `dmn/<name>.dmn` on every attempt — before validation and regardless of escalation. When the in-memory results list is empty, `assembly._collect_from_output_dir` globs all `dmn/*.dmn` and ships them, including failing/escalated attempts and with no metadata. Only deliver validated, accepted DMN. |
| SSRF: delivery target taken from request body | Not started | cpg-ingester | `services/delivery_svc.py:55` uses `data.get("acp_writer_url") or ACP_WRITER_URL`, letting a caller redirect CPGMetadata + recommendations (clinical content) to an arbitrary reachable host. In the pod-split model the delivery pod is the one component with egress. Pin the destination to env/config; do not accept it from the request. |
| Guideline Resolver can't see in-process models (single-pod) | Not started | acp-writer | `guideline_resolver.py:114` always fetches models over HTTP from `DECISION_ENGINE_URL` while `dmn_executor.py`/api use the in-process `_dynamic_models` dict. In the default single-pod deploy that host doesn't resolve, so `all_models = []` and no DMN is ever executed. Compounds the pod-split "DMN model discovery" item above, but also breaks the monolith. Fix: read models from the same source the executor uses, or a shared registry both paths query. |
| CarePlan omits `addresses` (patient Conditions) | Not started | acp-writer | `fhir_bundle_builder.py:205` builds CarePlan without `addresses=[Conditions]` (design Node 7). The semantic reviewer is prompted to check "addresses match conditions" — a check that can never pass. Populate `addresses` from the scanned condition references. |
| Production startup auto-seeds sample clinical data | Not started | acp-writer | `api.py:75` → `_setup_sample_data()` (`ui/app.py:68`) injects fixture guidelines, golden DMNs, and a recommendation bundle into the live stores whenever the registry is empty — on every fresh boot. For a clinical service this is a data-integrity hazard; gate it behind an explicit dev/demo flag. |
| compose default profile can't reach the LLM | Not started | deploy | The default-profile `acp-writer` service in `compose.yml` neither depends on nor receives `LITELLM_URL`, so `get_llm` falls back to `localhost:4000` and reasoning nodes fail on a plain `docker compose up`. (The pod-split `cpg-ingester-llm` sets it correctly.) Add `LITELLM_URL` and a litellm dependency to the single-pod services. |
| CPGMetadata contract drift vs approved design | Not started | shared | Code diverges from the approved contract-proposal: `CPGMetadata.supersedes` is `list[str]` where Contract 1 specifies `str`, and the `archetype`/`GuidelineArchetype` enum was dropped although the Structure Analyzer still detects archetype. Reconcile the code and the design doc (pick one representation and update the other). |

---

## Open Spikes and Research Items

| Item | Phase | Status | Notes |
|---|---|---|---|
| Agent framework evaluation | 2 | ✅ Complete | LangGraph selected. See `dev_docs/spikes/spike-agent-framework.md` |
| Praxis investigation | 2 | ✅ Complete | Too early. Track for Phase 6. See `dev_docs/spikes/spike-praxis.md` |
| Effective FHIR CarePlan goals | 3 | ✅ Complete | Implemented in acp-writer Plan Composer |
| AI Transparency on FHIR IG | 3 | ✅ Complete | AIAST/CLINAST_AIRPT implemented |
| Recommendation contract format | 3 | ✅ Complete | `cpg_contracts.recommendations` v1.0 |
| SonataFlow orchestration | 3.3 | ✅ Complete | Async callbacks, HTTP CloudEvents. See `dev_docs/spikes/spike-sonataflow-orchestration.md` |
| MCP Gateway governance | 3.3 | ✅ Complete | 12 tools, 3 virtual servers. See `dev_docs/spikes/spike-mcp-gateway.md` |
| Artifact store (MinIO) | 3.3 | ✅ Complete | PHI-segmented buckets. See `dev_docs/spikes/spike-artifact-store.md` |
| Async callback pattern | 3.3 | ✅ Complete | HTTP CloudEvents, no Kafka. See `dev_docs/spikes/spike-async-callback.md` |
| UI technology + design system | 4 | Not started | PatternFly 6 + React + TypeScript. Spike A. |
| UI ↔ backend interaction pattern | 4 | Not started | Async communication, human-in-the-loop. Spike B. |
| cpg-ingester UX design | 4 | Not started | Wireframes + flow diagrams. Spike C. |
| acp-writer UX design | 4 | Not started | Wireframes + flow diagrams. Spike D. |
| mock-EHR research (Medplum) | 4 | Not started | Medplum vs HAPI+components vs custom. Spike E. |
| Self-hosted models vs. frontier | 6 | Not started | Evaluate using smaller models (via vLLM) for cost, latency, and data locality |
| BPMN-to-Ansible conversion | 8 | Not started | Feasibility and approach |
