# Contract Proposal: cpg-ingester ↔ acp-writer

**Date:** 2026-07-20
**Status:** Approved — design decisions resolved, ready for implementation
**Context:** Phase 3.0 gate — these contracts must be defined before Phase 3.1 (cpg-ingester) and Phase 3.2 (acp-writer) can proceed independently.

---

## Principles

1. **Neither component imports from the other.** All contracts live in `shared/`.
2. **Standards as contracts.** DMN is the standard for computable decisions. The recommendation contract defined here is the standard for non-computable content.
3. **Computable criteria belong in DMN, not recommendations.** Population applicability criteria (age ranges, diagnosis codes, lab thresholds) are decision inputs. Only non-computable scope notes travel with recommendations.
4. **Metadata is not optional.** A recommendation without certainty, source, and type metadata is unusable for care plan generation.
5. **The contracts must support independent testing.** cpg-ingester validates output against contract schemas. acp-writer tests against hand-crafted fixture data.
6. **Contracts are versioned from the start.** Top-level ingestion payloads carry a `contract_version` field. New optional fields do not require a version bump. New required fields or breaking changes do.

---

## Communication Surface

cpg-ingester sends two categories of artifacts to acp-writer:

```
cpg-ingester ──── DMN XML ────────────► acp-writer (decision engine)
             ├─── Recommendations ────► acp-writer (vector store)
             └─── CPG Metadata ───────► acp-writer (guideline registry)
```

Each has its own contract. All three flow through acp-writer's REST API (and MCP tools), using contract types defined in `shared/`.

---

## Contract 1: CPG Metadata

Guideline-level information that applies to all artifacts extracted from a single CPG. Sent once per ingested guideline. Both decision models and recommendations reference this by `cpg_id`.

```python
class GradingSystem(str, Enum):
    GRADE = "GRADE"
    COR_LOE = "COR-LOE"
    GRADE_COR_HYBRID = "GRADE-COR-hybrid"
    SIMPLIFIED = "simplified"
    VERB_IMPLIED = "verb-implied"
    UNGRADED = "ungraded"

class GuidelineArchetype(str, Enum):
    INSTITUTIONAL = "institutional"
    JOURNAL_ARTICLE = "journal-article"
    MULTI_MODULE = "multi-module"
    FOCUSED_POLICY = "focused-policy"

CONTRACT_VERSION = "1.0"

class CPGMetadata(BaseModel):
    contract_version: str = CONTRACT_VERSION
    cpg_id: str                          # e.g., "SYN-HTN-2026-001"
    title: str
    version: str | None = None
    publication_date: date | None = None
    evidence_review_date: date | None = None  # "based on evidence reviewed through..."
    issuing_body: str | None = None       # kept generic, not used for filtering
    archetype: GuidelineArchetype | None = None
    grading_system: GradingSystem | None = None
    scope: str | None = None              # target population / clinical condition
    supersedes: str | None = None         # cpg_id of the guideline this replaces
```

**Why this exists separately from recommendations:** A single CPG produces many decision models and many recommendations. The guideline-level metadata (grading system, archetype, scope) applies to all of them and should not be duplicated on every artifact.

**API endpoints:**
- `POST /api/v1/guidelines` → register a CPG, returns `cpg_id`
- `GET /api/v1/guidelines` → list all registered guidelines
- `GET /api/v1/guidelines/{cpg_id}` → retrieve a single guideline
- `DELETE /api/v1/guidelines/{cpg_id}` → remove a guideline and cascade-delete its associated recommendations and decision models

---

## Contract 2: Decision Models (DMN) — existing, with refinements

The DMN boundary already works. The contract types exist in `shared/cpg_contracts/decisions.py`. Proposed refinements based on the CPG analysis:

```python
class DecisionCategory(str, Enum):
    TREATMENT = "treatment"
    SCREENING = "screening"
    MONITORING = "monitoring"
    RISK_ASSESSMENT = "risk-assessment"
    DIAGNOSTIC = "diagnostic"

class DecisionVariable(BaseModel):
    name: str
    type: str                            # "string", "number", "boolean"
    description: str | None = None       # what this variable represents clinically
    codes: list[str] | None = None       # SNOMED/LOINC codes for this variable

class DecisionModelSummary(BaseModel):
    id: str                              # globally unique (GUID), assigned by cpg-ingester
    name: str
    inputs: list[DecisionVariable]
    outputs: list[DecisionVariable]
    deployed_at: datetime | None = None
    source_cpg: str | None = None        # cpg_id reference
    category: DecisionCategory | None = None
    modifies: list[str] | None = None    # ids of models this overrides for a subpopulation
```

### Refinements from the CPG analysis

1. **`description` on DecisionVariable** — clinicians need to know what "Systolic BP" means in context (office measurement? ambulatory? home?). The CPG analysis found that measurement technique directly affects threshold validity.

2. **`codes` on DecisionVariable** — SNOMED/LOINC codes enable acp-writer to map FHIR patient data to DMN inputs automatically instead of relying on hardcoded field names.

3. **`category` on DecisionModelSummary** — the CPG analysis identified distinct decision types (treatment selection, screening criteria, monitoring schedules, risk stratification). acp-writer needs to know what kind of decision this is to place it correctly in the care plan.

4. **`modifies` on DecisionModelSummary** — the CPG analysis found that subpopulation recommendations are patches/overrides of general recommendations. A CKD-specific treatment decision *modifies* the general treatment decision — and may also modify the general monitoring decision. This is a list because a single subpopulation model can override multiple base models. The relationship must be explicit so acp-writer can apply the right override chain for a patient's condition profile.

**API endpoint:** `POST /api/v1/decisions/models` (existing) — accepts DMN XML, returns `DecisionModelSummary`

**Transport:** DMN XML is the artifact. The contract types describe the metadata extracted from it.

---

## Contract 3: Recommendations — new

This is the TBD boundary from AGENTS.md. Based on the CPG analysis, recommendations need structured metadata to be useful for care plan generation.

### Core types

```python
class RecommendationStrength(str, Enum):
    STRONG_FOR = "strong-for"
    CONDITIONAL_FOR = "conditional-for"
    CONSENSUS = "consensus"
    NO_RECOMMENDATION = "no-recommendation"
    CONDITIONAL_AGAINST = "conditional-against"
    STRONG_AGAINST = "strong-against"

class EvidenceQuality(str, Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    VERY_LOW = "very-low"
    UNGRADED = "ungraded"

class RecommendationType(str, Enum):
    TREATMENT = "treatment"
    DIAGNOSTIC = "diagnostic"
    MONITORING = "monitoring"
    LIFESTYLE = "lifestyle"
    EDUCATIONAL = "educational"
    REFERRAL = "referral"
    SCREENING = "screening"
    CONTRAINDICATION = "contraindication"
    PROCESS = "process"           # workflow/procedural steps

class CertaintyGrade(BaseModel):
    strength: RecommendationStrength
    evidence_quality: EvidenceQuality
    grading_system: GradingSystem | None = None  # if None, inherit from CPGMetadata
    original_grade: str | None = None  # e.g., "1A", "Strong for, moderate certainty"

class CrossReferenceRelationship(str, Enum):
    PREREQUISITE = "prerequisite"       # target must be satisfied before this applies
    ALTERNATIVE = "alternative"         # target is an alternative to this
    CONFLICTS_WITH = "conflicts-with"   # target and this give conflicting guidance
    MODIFIES = "modifies"               # this overrides/patches the target
    RELATED = "related"                 # informational link
    SUPERSEDES = "supersedes"           # this replaces the target
    OTHER = "other"                     # escape hatch — use description for context

class CrossReference(BaseModel):
    target_id: str                     # GUID of the referenced recommendation or decision model
    relationship: CrossReferenceRelationship
    description: str | None = None

class RecommendationProvenance(str, Enum):
    REVIEWED = "reviewed"              # evidence reviewed, recommendation unchanged
    NEW_ADDED = "new-added"            # new recommendation in this version
    AMENDED = "amended"                # recommendation changed based on new evidence
    NOT_CHANGED = "not-changed"        # not reviewed in this update cycle
    REMOVED = "removed"                # recommendation withdrawn

class Recommendation(BaseModel):
    id: str                            # globally unique (GUID)
    source_cpg: str                    # cpg_id reference
    section: str | None = None         # section reference within the CPG (e.g., "3.4", "Rec 12")
    title: str
    content: str                       # the recommendation text (plain text or markdown)
    recommendation_type: RecommendationType
    certainty: CertaintyGrade | None = None
    scope_notes: str | None = None     # non-computable applicability caveats
    remarks: list[str] | None = None   # structured implementation context bullets
    rationale: str | None = None       # why this recommendation was made
    cross_references: list[CrossReference] | None = None  # best-effort; acp-writer also uses semantic search
    provenance: RecommendationProvenance | None = None
    evidence_review_date: date | None = None  # when the evidence for THIS recommendation
                                               # was last reviewed (may differ from CPG date)
```

### Bundle type for batch ingestion

```python
class RecommendationBundle(BaseModel):
    contract_version: str = CONTRACT_VERSION
    source_cpg: str                    # cpg_id reference
    recommendations: list[Recommendation]
```

### Design decisions explained

**Why `content` is a single string, not structured sub-fields:** The CPG analysis found that recommendation content ranges from one-line statements to multi-paragraph guidance with embedded lists. Forcing structure (e.g., separate `action`, `condition`, `population` fields) would require the extraction system to decompose natural language into a schema that doesn't match how CPGs are written. Instead, the content is the recommendation as extracted, and the structured metadata (`recommendation_type`, `certainty`, `cross_references`) provides the machine-readable dimensions.

**Why `certainty` is a nested object, not flat fields:** The normalized certainty schema maps five different grading systems into a common representation. The `original_grade` preserves the source system's exact label so nothing is lost in normalization. This was a key finding from the CPG analysis — the two-axis structure (strength × evidence quality) is universal but the labels vary dramatically.

**Why `no-recommendation` is a strength value:** The CPG analysis validation found that formal "no recommendation for or against" is a distinct output that needs explicit capture — different from silence (topic not addressed) and from a conditional recommendation.

**Why `remarks` is a separate field:** The validation found structured bulleted "Remarks" sections attached to individual recommendations with practical implementation details. These sit between the recommendation and the evidence discussion and are a distinct extraction target.

**Why `scope_notes` is a string, not structured:** Non-computable applicability caveats ("studied primarily in US veterans", "limited evidence in pregnant populations") are free text by nature. Computable criteria belong in DMN, not here.

**API endpoints:**
- `POST /api/v1/knowledge/recommendations` → ingest a single recommendation
- `POST /api/v1/knowledge/recommendations/batch` → ingest a `RecommendationBundle`
- `GET /api/v1/knowledge/recommendations?source_cpg=...` → list by CPG
- `GET /api/v1/knowledge/recommendations/{id}` → retrieve full recommendation by GUID
- `POST /api/v1/knowledge/search` → semantic search (returns `RecommendationSummary`, not full objects)

---

## Contract 4: Search — refinement of existing

The existing `KnowledgeSearchRequest` / `KnowledgeSearchResponse` need updates to surface the new metadata:

```python
class RecommendationSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    source_cpg: str | None = None         # scope to a specific CPG
    recommendation_type: RecommendationType | None = None  # filter by type
    strength_in: list[RecommendationStrength] | None = None  # only return these strengths

class RecommendationSummary(BaseModel):
    id: str
    title: str
    source_cpg: str
    recommendation_type: RecommendationType
    certainty: CertaintyGrade | None = None

class RecommendationSearchResult(BaseModel):
    recommendation: RecommendationSummary  # summary for scanning; full details via GET by id
    score: float                           # similarity score
    excerpt: str | None = None             # highlighted matching text

class RecommendationSearchResponse(BaseModel):
    results: list[RecommendationSearchResult]
```

**Why type and strength filters:** acp-writer composes care plans by type — it needs treatment recommendations separately from lifestyle recommendations. The `strength_in` filter takes an explicit list of strength values (e.g., `["strong-for", "conditional-for"]`) rather than a `min_strength` floor, because strength values mix direction and intensity — `strong-against` is not weaker than `conditional-for`, it's a different direction.

**Why summaries in search results:** Search results return `RecommendationSummary` (id, title, source_cpg, type, certainty) rather than full `Recommendation` objects. Full details including content, remarks, rationale, and cross-references are retrieved via `GET /api/v1/knowledge/recommendations/{id}` once the caller decides which results to inspect.

---

## What does NOT cross this boundary

These are internal to one component and do not appear in the contracts:

- **Vector store implementation** — internal to acp-writer (Milvus, pgvector, etc.)
- **Extraction pipeline state** — internal to cpg-ingester (LangGraph graph state, agent outputs)
- **Embedding model choice** — internal to acp-writer
- **Docling parse output** — internal to cpg-ingester (Markdown, JSON)
- **LLM prompts** — internal to cpg-ingester
- **FHIR CarePlan structure** — output of acp-writer, not part of this boundary
- **Patient data** — input to acp-writer from mock-EHR, not from cpg-ingester

---

## How the contracts relate

```
                    CPGMetadata
                    (registered once per guideline)
                         │
            ┌────────────┼────────────┐
            │            │            │
     DecisionModel   Recommendation  Recommendation
     (DMN XML +      (treatment)     (lifestyle)
      metadata)           │               │
            │            └───────────────┘
            │                    │
            │         ┌─────────┴──────────┐
            │         │  CrossReference    │
            │         │  (links between    │
            │         │   recommendations  │
            │         │   and/or decisions) │
            │         └────────────────────┘
            │
       modifies ──► DecisionModel
       (subpopulation override)
```

A `CPGMetadata` is the parent. It has many `DecisionModel`s and many `Recommendation`s. Decision models can modify other decision models (subpopulation overrides). Recommendations can cross-reference other recommendations or decision models.

---

## Changes to existing contracts

| What | Change | Reason |
|---|---|---|
| `DecisionVariable` | Add `description`, `codes` | Clinical context and FHIR mapping |
| `DecisionModelSummary` | Add `category` (enum), `modifies` (list), use GUID `id` | Decision type classification, subpopulation override chain, cross-referenceable IDs |
| `KnowledgeDocument` (OpenAPI) | Replace with `Recommendation` | Structured metadata instead of freeform `metadata: {}` |
| `KnowledgeSearchRequest` | Replace with `RecommendationSearchRequest` | Type and strength filtering |
| `KnowledgeSearchResponse` | Replace with `RecommendationSearchResponse` | Summary objects in results, not full recommendations |
| AGENTS.md | Change "Recommendations: TBD" to the contract name | Close the open boundary |

### What stays the same

| What | Why |
|---|---|
| DMN XML as the artifact format | DMN is the standard; the contract types describe metadata, not the artifact |
| `DecisionEvaluationRequest` / `Response` | Evaluation contract is between acp-writer and its internal decision engine, not part of the ingester↔writer boundary |
| `PatientSummary` (fhir.py) | This is the mock-EHR↔acp-writer boundary, not ingester↔writer |
| REST API structure | Same endpoint patterns, updated schemas |

---

## File layout in `shared/`

```
shared/src/cpg_contracts/
├── __init__.py          # re-exports all types, defines CONTRACT_VERSION
├── decisions.py         # DecisionVariable, DecisionModelSummary, DecisionCategory,
│                        # DecisionEvaluationRequest/Response (refined)
├── recommendations.py   # NEW: Recommendation, RecommendationBundle, RecommendationSummary,
│                        # CertaintyGrade, CrossReference, CrossReferenceRelationship,
│                        # RecommendationProvenance, RecommendationStrength,
│                        # EvidenceQuality, RecommendationType enums
├── guidelines.py        # NEW: CPGMetadata, GradingSystem, GuidelineArchetype
├── search.py            # NEW: RecommendationSearchRequest/Response/Result
└── fhir.py              # PatientSummary (unchanged — different boundary)
```

---

## Design decisions (resolved)

1. **`Recommendation.content` is plain text or markdown.** No structured sub-fields. Markdown formatting (bullet lists, headers) is preserved from extraction. The structured metadata fields (`recommendation_type`, `certainty`, `cross_references`) provide the machine-readable dimensions.

2. **All `id` fields are globally unique (GUIDs).** `Recommendation.id`, `DecisionModelSummary.id`, `CrossReference.target_id` — all use GUIDs. cpg-ingester generates IDs at extraction time; acp-writer preserves them as-is (does not derive or overwrite). This avoids namespace collisions and ensures cross-references remain valid. Note: the existing `api.py` code that derives IDs from DMN model names must be updated to accept the incoming ID.

3. **`DecisionModelSummary.modifies` is a list.** A model can modify multiple base models (e.g., a CKD-specific model that overrides both the general treatment model and the general monitoring model).

4. **`CertaintyGrade` includes `grading_system`.** Some CPGs use multiple evidence assessment methods within the same guideline (e.g., GRADE for quantitative evidence plus GRADE-CERQual for qualitative findings). The system identifier travels with each recommendation rather than being inherited solely from `CPGMetadata`. If `grading_system` is None, inherit from `CPGMetadata.grading_system`.

5. **Contraindications are a recommendation type**, not a separate contract type. `recommendation_type: "contraindication"` with `cross_references` linking to the treatment recommendation being negated. The `relationship: "modifies"` on the cross-reference makes the override relationship explicit.

6. **Contracts are versioned.** `CPGMetadata` and `RecommendationBundle` carry a `contract_version` field (default `CONTRACT_VERSION = "1.0"`). Versioning policy: adding optional fields = no version bump; adding required fields or removing/renaming fields = version bump. acp-writer should validate `contract_version` on ingestion and reject payloads from incompatible versions.

7. **All enum-typed fields use validated enums, not free strings.** `CrossReference.relationship`, `Recommendation.provenance`, `DecisionModelSummary.category`, `RecommendationStrength`, `EvidenceQuality`, `RecommendationType` — all are `str, Enum` subclasses. This ensures validation at serialization boundaries and prevents drift between producer and consumer.

8. **Search returns summaries, not full objects.** `RecommendationSearchResult` contains a `RecommendationSummary` (id, title, source_cpg, type, certainty). Full recommendation details retrieved via `GET /api/v1/knowledge/recommendations/{id}`. This keeps search payloads small.

9. **`cross_references` is best-effort.** cpg-ingester populates cross-references where it can reliably detect them, but completeness is not guaranteed. acp-writer should also use semantic search to discover related recommendations.
