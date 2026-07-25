# acp-writer Multi-Agent Care Plan Composition Design

## Overview

acp-writer composes patient-specific, FHIR-compliant care plans by combining clinical decision logic (DMN), retrieved recommendations (vector store), and patient data (FHIR IPS). The pipeline uses a two-phase architecture: a **clinical reasoning phase** that determines what belongs in the care plan, followed by a **FHIR generation phase** that produces validated, AI-Transparency-compliant FHIR resources.

**Framework:** LangGraph `StateGraph` (as library, not LangGraph Server)
**Tracing:** `mlflow.langchain.autolog()` — every node execution traced automatically
**Contracts:** `shared/src/cpg_contracts/` — CPGMetadata, Recommendation, DecisionModelSummary, SourceLocation
**Standards:** FHIR R4, AI Transparency on FHIR IG (HL7 STU1)

## Architecture

```
═══════ PHASE 1: CLINICAL REASONING ═══════

                    FHIR IPS
                      │
                      ▼
           ┌────────────────────┐
           │  Condition Scanner │  Lightweight, deterministic:
           └───────┬────────────┘  Extracts condition codes + demographics
                   │               NO full IPS parse (avoids context bloat)
                   ▼
           ┌────────────────────┐
           │ Guideline Resolver │  Identifies applicable CPGs
           └───────┬────────────┘  Matches condition codes to CPGMetadata
                   │               Identifies relevant DMN models
                   │               Builds DMN dependency graph
                   ▼
           ┌────────────────────┐
           │  DMN Executor      │  Calls decision models
           └───────┬────────────┘  For each model:
                   │                 1. Determine required inputs
                   │                 2. Extract specific data from IPS
                   │                    (targeted, not full parse)
                   │                 3. Call model via JIT endpoint
                   │                 4. Record inputs/outputs verbatim
                   │               Resolves dependency graph
                   │               Parallelizes independent calls
                   ▼
        ┌──────────────────────────┐
        │ Recommendation Retriever │  Searches vector store
        └───────┬──────────────────┘  By condition + DMN outcomes
                │                     Filters by type and strength
                │                     Returns full Recommendation objects
                ▼
        ┌──────────────────────────┐
        │    Plan Composer         │  Maps decisions + recs → goals + activities
        └───────┬──────────────────┘  Resolves recommendation-embedded DMN
                │                     Assigns FHIR codes (with terminology API)
                │                     Detects potential conflicts (placeholder)
                │                     Produces structured Planning Brief
                ▼
        ┌──────────────────────────┐
        │    Brief Reviewer        │  Adversarial (max 2 loops)
        └───────┬──────────────────┘  Checks clinical coherence
                │                     Verifies completeness
                │                     Validates contraindications
                ▼
         Planning Brief (approved)


═══════ PHASE 2: FHIR GENERATION + VALIDATION ═══════

         Planning Brief
                │
                ▼
        ┌──────────────────────────┐
        │  FHIR Bundle Generator   │  Deterministic (code, not LLM):
        └───────┬──────────────────┘  - CarePlan resource
                │                     - Goal resources
                │                     - MedicationRequest / ServiceRequest
                │                     - AI Device (AI Transparency IG)
                │                     - AI Provenance (full lineage)
                │                     - AIAST meta.security on all resources
                ▼
        ┌──────────────────────────┐
        │ Terminology Validator    │  Deterministic:
        └───────┬──────────────────┘  SNOMED via tx.fhir.org
                │                     RxNorm via rxnav.nlm.nih.gov
                │                     LOINC/ICD-10 via NLM Clinical Tables
                │                     Fix invalid codes, flag unresolvable
                ▼
        ┌──────────────────────────┐
        │  FHIR Syntax Validator   │  Deterministic:
        └───────┬──────────────────┘  Required fields, reference resolution
                │                     Profile URLs, code completeness
                ▼
        ┌──────────────────────────┐
        │ FHIR Semantic Reviewer   │  LLM (max 2 loops):
        └───────┬──────────────────┘  Clinical coherence
                │                     Goals ↔ activities consistency
                │                     AI Transparency completeness
                ▼
        ┌──────────────────────────┐
        │  FHIR Server Writer      │  POST Bundle to HAPI FHIR
        └──────────────────────────┘  Validate response
```

## Phase 1: Clinical Reasoning

Phase 1 determines **what** goes in the care plan. The output is a structured Planning Brief — not FHIR, but a well-defined intermediate format that Phase 2 can serialize deterministically.

### Node 1: Condition Scanner

A lightweight, deterministic first pass over the IPS. Extracts only what's needed to determine which guidelines apply — **not** a full patient data parse.

**Inputs:** FHIR Bundle (IPS or raw Bundle)
**Outputs:**
- Patient demographics (age, gender, patient reference)
- Active condition codes (SNOMED/ICD-10 code + display, from `Condition.code`)
- Active medication codes (from `MedicationStatement` or `MedicationRequest`)
- Allergy codes (from `AllergyIntolerance.code`)

This is pure FHIR traversal — no LLM, no deep extraction. It scans resource types and pulls coded fields. The full IPS stays in state for targeted extraction later, but only condition/medication/allergy codes enter the reasoning chain at this point.

**Why not a full parse:** An IPS can contain hundreds of observations, decades of history, and conditions unrelated to any registered CPG. Parsing everything upfront wastes context and introduces noise. Instead, specific data points are extracted on-demand by the DMN Executor when it knows what it needs.

### Node 2: Guideline Resolver

Determines which registered CPGs and DMN models apply to this patient's conditions.

**Inputs:** Patient condition codes, registered CPGMetadata list, deployed DecisionModelSummary list
**Outputs:**
- Applicable CPGs (matched by patient condition codes vs CPG scope)
- Applicable DMN models (matched by DecisionCategory and patient conditions)
- DMN dependency graph (if model B needs model A's output)

This node queries the guidelines registry (`GET /api/v1/guidelines`) and decision model list (`GET /api/v1/decisions/models`) to build the execution plan. The `DecisionModelSummary.modifies` field provides dependency information.

### Node 3: DMN Executor

Executes all applicable DMN models against patient data, extracting only the specific data points each model requires from the IPS.

**Inputs:** Full IPS (for targeted extraction), applicable DMN models (ordered by dependencies)
**Outputs:** Decision results with full audit trail (including which patient data was used)

**Execution strategy:**
1. Build dependency graph from `DecisionModelSummary.modifies`
2. For each model (in topological order):
   a. Determine required inputs from `DecisionModelSummary.inputs` (variable names, types, descriptions)
   b. **Targeted extraction:** pull only the specific values needed from the IPS (e.g., most recent systolic BP observation, active diabetes condition). This is the "ask the IPS a question" pattern from cpg-to-careplanwriter's IPS subagent.
   c. Call model via JIT endpoint with extracted inputs
   d. Record: model ID, model name, exact inputs extracted (with FHIR resource references for audit), exact outputs, timestamp
3. Parallelize independent calls (models with no mutual dependencies)
4. On failure: record error, apply CPG-consistent default, document the default and its rationale

The targeted extraction approach means only clinically relevant patient data enters the pipeline. Each data point extracted is traceable to a specific FHIR resource in the IPS, which flows through to the Provenance chain.

Uses the existing JIT endpoint (`/jit/dmn`) for dynamic evaluation.

### Node 4: Recommendation Retriever

Searches the vector store for recommendations relevant to this patient's conditions and decision outcomes.

**Inputs:** Patient conditions, DMN results, applicable CPG IDs
**Outputs:** Ranked list of `Recommendation` objects with source locations and certainty grades

**Search strategy:**
- Primary search: by patient condition + DMN outcome text (semantic similarity)
- Filters: `source_cpg` (limit to applicable CPGs), `recommendation_type` (match clinical context)
- Strength filter: prioritize `strong-for` and `conditional-for`
- Returns full `Recommendation` objects including `certainty`, `cross_references`, `source_location`, `remarks`

Uses `POST /api/v1/knowledge/search` (the `RecommendationSearchRequest` contract).

### Node 5: Plan Composer

The core clinical reasoning step. Maps decisions and recommendations into a structured Planning Brief.

**Inputs:** Patient summary, DMN results (with audit trail), retrieved recommendations
**Outputs:** Planning Brief containing:
- Goals (with target measures, target values, source recommendation IDs)
- Activities:
  - Medications (drug, dose, route, frequency, source recommendation)
  - Monitoring (labs, vitals, frequency, source recommendation)
  - Lifestyle modifications (description, source recommendation)
  - Referrals (specialty, reason, source recommendation)
  - Process activities (workflow, quality measures)
- FHIR codes for each item (verified via terminology API)
- Provenance chain (which CPG, which recommendation, which DMN call led to each item)
- Potential conflicts (same goal from different sources, overlapping activities)

**Recommendation refinement:** Some recommendations contain embedded decision logic (e.g., "if eGFR < 45, reduce dose"). The Plan Composer identifies these and calls additional DMN models or applies rule-based logic to refine the recommendation for this specific patient.

**Terminology resolution:** The Plan Composer resolves FHIR codes during composition, not as a post-hoc fix. Uses a terminology lookup tool (modeled on fhir-ips-writer's `terminology_lookup.py`):
- SNOMED CT via `tx.fhir.org/r4` (ValueSet/$expand, CodeSystem/$lookup)
- RxNorm via `rxnav.nlm.nih.gov/REST` (3-tier: exact → normalized → approximate)
- LOINC via `clinicaltables.nlm.nih.gov`
- ICD-10-CM via `clinicaltables.nlm.nih.gov`
- "Never trust the LLM's memory" — every code must be API-verified

### Node 6: Brief Reviewer (Adversarial)

Independent LLM review of the Planning Brief before FHIR generation.

**Checks:**
- Clinical coherence: do goals match activities? Are all conditions addressed?
- DMN input verification: were the right values used? Right units?
- Recommendation completeness: are all strong-for recommendations included?
- Contraindication check: does any activity conflict with patient allergies or conditions?
- Code verification: are the assigned FHIR codes clinically appropriate?

**Persona:** Clinical pharmacist reviewing a care plan draft (different persona from the Plan Composer).

**Protocol:** Structured APPROVE/REVISE response. On REVISE, numbered objections with specific fixes. Max 2 rounds, then proceed with unresolved items flagged.

### Planning Brief Format

The Planning Brief is a **formal Pydantic model** — the contract between the LLM reasoning layer (Phase 1) and the deterministic FHIR generation layer (Phase 2). Because the FHIR Bundle Generator is pure code with no LLM to interpret ambiguity, its input must be unambiguous and schema-validated. This is the same pattern as fhir-ips-writer's declarative JSON spec → `build_ips_bundle.py`.

The Planning Brief is defined as Pydantic types (likely in `acp_writer/planning_brief.py` or `shared/cpg_contracts/`). The Brief Reviewer validates against this schema deterministically before doing the LLM clinical coherence check — a free gate that catches structural issues before spending tokens on semantic review.

**The brief carries more than what ends up in FHIR.** Phase 1's clinical reasoning captures context that the FHIR CarePlan cannot represent — detailed clinical rationale, step-by-step decision logic, process workflow descriptions, escalation paths, timing dependencies between activities, and actor/role assignments. This extra context is critical for BPMN generation in Phase 4: the BPMN Writer will need to know workflow sequencing, actor assignments, decision branching, and escalation paths that have no representation in FHIR CarePlan resources. By capturing this in the Planning Brief now, Phase 4 can operate directly on the brief without re-running clinical reasoning.

```json
{
  "patient_reference": "Patient/123",
  "applicable_cpgs": ["SYN-HTN-2026-001"],
  "dmn_audit_trail": [
    {
      "model_id": "...",
      "model_name": "Treatment Recommendation",
      "inputs": {"Systolic BP": 145, "Has Diabetes": true},
      "outputs": {"Action": "Start medication", "Medication": "Lisinopril"},
      "timestamp": "2026-07-21T..."
    }
  ],
  "goals": [
    {
      "description": "Lower blood pressure to target range",
      "target_measure_code": {"system": "http://loinc.org", "code": "8480-6"},
      "target_value": {"high": 140, "unit": "mmHg"},
      "source_recommendation_id": "rec-guid-123",
      "source_cpg": "SYN-HTN-2026-001"
    }
  ],
  "activities": [
    {
      "type": "medication",
      "description": "Start Lisinopril 10mg daily",
      "medication_code": {"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "29046"},
      "dose": "10 mg",
      "route": "oral",
      "frequency": "daily",
      "source_recommendation_id": "rec-guid-456",
      "source_cpg": "SYN-HTN-2026-001",
      "source_dmn_call": 0,
      "clinical_rationale": "ACE inhibitor selected due to renal protective effects in patient with diabetes",
      "workflow": {
        "actor": "prescribing_physician",
        "sequence_after": null,
        "escalation": "If BP not at target after 4 weeks, consider dose increase or addition of second agent",
        "monitoring_trigger": "BMP in 4 weeks to check renal function and electrolytes"
      }
    }
  ],
  "conflicts": [],
  "review_status": "approved"
}
```

## Phase 2: FHIR Generation

Phase 2 transforms the Planning Brief into a valid FHIR Bundle. The key design principle: **FHIR generation is deterministic code, not LLM generation.** This eliminates code hallucination entirely for the FHIR layer.

### Node 7: FHIR Bundle Generator

Deterministic Python code (not LLM) that produces a FHIR R4 Bundle from the Planning Brief.

**Produces:**
- **CarePlan** resource: status=draft, intent=proposal, category=assess-plan, addresses=[Conditions], goal=[Goals], activity=[Activities]
- **Goal** resources: one per goal in the brief, with `target.measure` (LOINC) and `target.detailRange`
- **Activity resources:**
  - MedicationRequest (from medication activities)
  - ServiceRequest (from monitoring, referral activities)
  - Inline `performedActivity` (from lifestyle, educational activities)
- **AI Device** resource (AI Transparency IG `AI-Device` profile):
  - `type` = Artificial-Intelligence
  - `AIKind` extension = Large-Language-Models
  - `manufacturer`, `version`, `deviceName`
- **AI Provenance** resource (AI Transparency IG `AI-Provenance` profile):
  - `target` = all generated resources
  - `reason` = AIAST
  - `agent[0]` = AI Device as `author`
  - `entity` entries: source IPS (`role: source`), source CPG (`role: derivation`), DMN call records
- **Per-activity Provenance** (one per activity with CPG source):
  - `target` = the specific activity (using `targetPath` extension for inline BackboneElements)
  - `entity.what` = recommendation ID with source_location
  - Activity code = `merge` from ProvenanceActivityType (if from multiple sources)
- **`meta.security`** on every generated resource: `{system: "http://terminology.hl7.org/CodeSystem/v3-ObservationValue", code: "AIAST"}`

All intra-bundle references use `urn:uuid:` fullUrls. The generator assigns UUIDs, wires all references, and produces valid FHIR without LLM involvement.

### Node 8: Terminology Validator

Deterministic safety check — verifies all FHIR codes in the generated bundle against public terminology servers.

**Per-system strategy (from fhir-ips-writer):**
- **SNOMED CT:** `tx.fhir.org/r4` — CodeSystem/$lookup for verification
- **RxNorm:** `rxnav.nlm.nih.gov/REST` — rxcui lookup for verification
- **LOINC:** `clinicaltables.nlm.nih.gov` — search verification
- **ICD-10-CM:** `clinicaltables.nlm.nih.gov` — search verification

On invalid code: attempt to find the correct code and fix it. On unresolvable: flag in a `CarePlan.note` entry ("Code verification gap: [system] [code] could not be verified").

### Node 9: FHIR Syntax Validator

Deterministic structural checks (modeled on fhir-ips-writer's `validate_bundle.py`):
- Bundle has required fields (type, identifier, timestamp)
- Every resource has an `id`
- All internal references resolve
- Required fields per resource type (CarePlan, Goal, MedicationRequest, ServiceRequest)
- All coded fields have `system` and `code`
- AI Transparency: all resources have AIAST `meta.security`, AI-Device exists, AI-Provenance exists
- Provenance targets reference actual resources in the bundle

### Node 10: FHIR Semantic Reviewer

LLM review of the complete FHIR Bundle for clinical coherence.

**Checks:**
- Every Goal has at least one Activity that works toward it
- Every Activity has a corresponding Goal (or is a process activity)
- Medication doses are clinically reasonable
- Monitoring frequencies are appropriate
- AI Transparency Provenance is complete (all resources targeted, all sources listed)
- CarePlan `addresses` references match the patient's actual conditions

**Retry loop:** Max 2 rounds. On REVISE, the FHIR Bundle Generator re-runs with specific fixes.

### Node 11: FHIR Server Writer

Posts the validated Bundle to the HAPI FHIR server.

- POST transaction Bundle to FHIR server
- Validate server response (check for OperationOutcome errors)
- Store care plan reference for retrieval
- Support for the approve/reject workflow:
  - On approve: update CarePlan.status to `active`, change `meta.security` from AIAST to CLINAST_AIRPT, add clinician as `verifier` agent on Provenance
  - On reject: update status, record reason in CarePlan.note

## Conflict Resolution (Deferred — Phase 4)

When multiple CPGs produce recommendations for the same patient, conflicts can arise. The conflict resolver will:

1. Classify conflicts: Same, Complement, Conflict, Unchanged (from careplan-combiner)
2. For Conflict: present to clinician with resolution options (never auto-resolve)
3. Track resolution in Provenance: `entity.role = "removal"` for discarded items, user's instruction in `Provenance.note` with `authorString = "user"`

This is deferred because Phase 3.2 focuses on single-CPG care plan generation. Multi-CPG conflict resolution requires Phase 3.3 integration.

## Vector Store Spike (Required before implementation)

The prompt specifies a spike for vector store selection. Options to evaluate:

| Option | Pros | Cons |
|---|---|---|
| **PostgreSQL + pgvector** | Robust, industry standard, open source, single database for metadata + vectors | May need tuning for semantic search performance |
| **Milvus** | Purpose-built for vector search, high performance | Additional infrastructure, less mature for metadata queries |
| **ChromaDB** | Simple, embedded, good for prototyping | Not production-grade for clinical data |

The user leans toward PostgreSQL. The spike should evaluate: semantic search quality, indexing performance, hybrid search (metadata filters + vector similarity), and operational complexity.

## BPMN Generation (Deferred — Phase 4)

Per the project plan, BPMN generation is deferred to Phase 4. The architecture supports it:
- Activities in the Planning Brief can carry BPMN references
- The FHIR Bundle Generator can add BPMN DocumentReference resources linked to CarePlan activities via extension
- A BPMN Writer node would slot in after the Plan Composer, operating on automatable activities

## Terminology Lookup Tool

A reusable tool (modeled on fhir-ips-writer's `terminology_lookup.py`) available to both the Plan Composer and the Terminology Validator:

**Modes:**
- `find(system, text)` → finds the best code for a clinical concept
- `verify(system, code)` → verifies a code exists and returns its display

**System support:**
- SNOMED CT: `tx.fhir.org/r4` (ValueSet/$expand for find, CodeSystem/$lookup for verify)
- RxNorm: `rxnav.nlm.nih.gov/REST` (3-tier: exact → normalized → approximate)
- LOINC: `clinicaltables.nlm.nih.gov/api/loinc_items/v3/search`
- ICD-10-CM: `clinicaltables.nlm.nih.gov/api/icd10cm/v3/search`

**Principles:**
- Never trust the LLM's memory for codes
- Coarsen-don't-fabricate: if a specific code can't be found, use a broader concept
- Network errors are reported, never fatal
- Cache results (30-day TTL)

## Review Strategy Summary

| Stage | Syntax (deterministic) | Semantic (LLM) |
|---|---|---|
| IPS Parsing | FHIR traversal | Ambiguous code resolution |
| Plan Composition | Terminology API verification | Clinical reasoning |
| Brief Review | — | Adversarial clinical review (max 2 loops) |
| FHIR Generation | Deterministic code (no LLM) | — |
| Terminology Validation | API verification | — |
| FHIR Syntax | Structural checks | — |
| FHIR Semantic | — | Clinical coherence review (max 2 loops) |

## AI Transparency on FHIR Compliance

Every care plan bundle includes:

1. **AIAST `meta.security`** on every generated resource (CarePlan, Goal, MedicationRequest, ServiceRequest, Provenance)
2. **AI Device** resource with `type = Artificial-Intelligence`, `AIKind = Large-Language-Models`
3. **AI Provenance** with:
   - `reason` = AIAST
   - `agent[0]` = AI Device as `author`
   - `entity` entries for: source IPS (`role: source`), source CPGs (`role: derivation`), DMN call audit trail
4. **Per-activity Provenance** linking each activity to its source recommendation and CPG location (via `source_location`)
5. **On clinician approval**: `meta.security` changes from AIAST to CLINAST_AIRPT, clinician added as `verifier` agent

## Deployment Model

Phase 3.2 deploys acp-writer as a **single pod** running the entire LangGraph pipeline in-process. Phase 3.3 (Integration and Governance) splits into pod-per-security-profile alongside OpenShell policy enforcement:

| Pod Group | Components | OpenShell Policy |
|---|---|---|
| **Patient Data** | Condition Scanner, targeted IPS extraction | Patient data access, no LLM |
| **LLM Reasoning** | Guideline Resolver, Plan Composer, Brief Reviewer, FHIR Semantic Reviewer | LLM (MaaS) + vector store, no FHIR server |
| **Decision Engine** | DMN Executor | Kogito access only |
| **FHIR Generation** | Bundle Generator, Terminology Validator, FHIR Syntax Validator | Terminology APIs only, no patient data |
| **FHIR Server** | FHIR Server Writer, Status Manager | FHIR server access only |

## Key Design Decisions

1. **FHIR generation is deterministic code.** LLMs reason about what goes in the care plan; code produces valid FHIR from the Planning Brief. This eliminates code hallucination — the single most dangerous failure mode for clinical FHIR resources (from fhir-ips-writer lessons).

2. **Planning Brief as formal Pydantic schema.** Clinical reasoning produces a schema-validated document, not FHIR. The brief is the contract between the LLM layer and the deterministic FHIR generator — because the generator is code with no LLM, its input must be unambiguous. The brief also carries context beyond what FHIR can represent (workflow sequencing, actor assignments, escalation paths, clinical rationale) which Phase 4's BPMN Writer will consume without re-running clinical reasoning.

3. **Lazy IPS extraction, not upfront parsing.** The Condition Scanner does a minimal first pass (condition codes + demographics only). The DMN Executor extracts specific data points on-demand as each model needs them. This avoids context bloat from large IPS documents with irrelevant data, and makes every extracted data point auditable (traceable to a specific FHIR resource in the IPS).

4. **Terminology verified during composition, not after.** The Plan Composer resolves codes via API before the FHIR layer. The Terminology Validator is a safety net, not the primary mechanism.

5. **AI Transparency is built in, not bolted on.** Device, Provenance, and AIAST tagging are first-class outputs of the FHIR Bundle Generator, not optional additions.

6. **Conflict resolution is deferred but designed for.** The Planning Brief includes a `conflicts` field. The architecture supports inserting a Conflict Resolver node before the Brief Reviewer in Phase 4.

7. **Approval workflow changes the AI Transparency tag.** AIAST (AI-asserted) → CLINAST_AIRPT (clinician-asserted from AI-reported) on approval, per the IG's intent.

8. **DMN audit trail flows through to Provenance.** Every DMN call is recorded verbatim and becomes a Provenance entity, enabling full lineage from care plan activity → recommendation → CPG → DMN evaluation → patient data.

9. **Vector store is pluggable.** The architecture references the vector store through the search API contract (`RecommendationSearchRequest/Response`). The actual store (PostgreSQL + pgvector, Milvus, etc.) is an internal implementation detail per AGENTS.md.

10. **Recommendation source_location enables CPG lineage.** The `SourceLocation` on each recommendation carries page numbers and bounding boxes from the original CPG PDF, flowing through to Provenance for complete lineage.

11. **Adversarial review at two levels.** The Brief Reviewer checks clinical reasoning; the FHIR Semantic Reviewer checks FHIR encoding. Different concerns, different personas, different retry loops.

## Lessons Applied from cpg-ingester

| cpg-ingester Pattern | How It's Applied Here |
|---|---|
| Two-phase architecture | Clinical reasoning → FHIR generation |
| Deterministic validation separate from LLM review | Terminology + syntax validators are code; semantic review is LLM |
| Adversarial review with heterogeneous prompting | Brief Reviewer (clinical pharmacist) ≠ Plan Composer |
| File output for review | Planning Brief and FHIR Bundle written to output directory |
| MemorySaver for dev | Resume-on-failure for long-running pipelines |
| Max 2 retry iterations | Same cap on review loops |
| Explicit escalation | Unresolvable items flagged, never silently accepted |
| Single pod now, multi-pod in Phase 3.3 | Pod-per-security-profile with OpenShell policies |

## Lessons Applied from Reference Skills

| Reference Skill | Pattern Applied |
|---|---|
| cpg-to-careplanwriter | Separation of clinical reasoning from FHIR serialization; critique loop; DMN audit trail; section-level CPG citations in Provenance |
| fhir-ips-writer | Terminology lookup with multi-system fallback; "never trust the LLM's memory"; deterministic FHIR builder from declarative spec; multi-coding support |
| careplan-combiner | Lean resource + audit Provenance; targetPath for inline activities; standard FHIR merge code; interactive conflict resolution with full audit trail |
