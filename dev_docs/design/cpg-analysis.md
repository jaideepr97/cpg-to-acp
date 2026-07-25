# Clinical Practice Guideline Analysis: Structure and Extraction Insights

**Date:** 2026-07-20 (validated 2026-07-20)
**Purpose:** Inform the design of cpg-ingester (extraction) and acp-writer (care plan generation) based on analysis of 42 real-world CPGs from 7 healthcare organizations, covering hypertension, diabetes, obesity, heart failure, CKD, pain management, mental health, and acute coronary syndromes. Validated against 6 additional CPGs (mental health, obesity, emergency medicine, pain) not in the original sample.

> This document describes patterns observed across CPGs generically. No specific organizations or documents are named.

---

## 1. Document Structure and Format Archetypes

CPGs follow a remarkably consistent high-level skeleton despite originating from very different organizations:

- **Front matter:** Title page, authorship/committee, version/date, disclaimers, table of contents
- **Methods/Methodology:** Evidence review process, search strategy, grading methodology (ranges from a few paragraphs to dozens of pages)
- **Background/Introduction:** Epidemiology, disease burden, rationale, target audience
- **Recommendations:** The core deliverable — organized either by clinical workflow (screen → diagnose → treat → monitor) or by patient subpopulation (by comorbidity or age group)
- **Evidence discussion:** Detailed summaries supporting each recommendation — may be inline, in a separate section, or in appendices
- **Research gaps:** Areas where evidence is insufficient
- **Implementation guidance:** Quality measures, performance metrics, workflow integration
- **References and appendices:** Evidence tables, GRADE assessments, search strategies, drug tables, patient-facing content

### Guideline format archetypes

The linear skeleton above applies to one archetype but not all. CPGs fall into four distinct format archetypes, each requiring a different parsing strategy:

| Archetype | Structure | Example characteristics |
|---|---|---|
| **Institutional standalone** | Linear, appendix-heavy | Single-column, branded, generous spacing. Follows the full skeleton. Most parser-friendly. |
| **Journal article** | Abstract-first, compact | Two-column, recommendations early, evidence as the body, minimal appendices. Supplement-dependent — detailed evidence tables often published separately. |
| **Multi-module intervention guide** | Hub-and-spoke, module-templated | Master routing chart dispatches to condition-specific modules. Each module follows an identical internal template (overview → assessment → management → follow-up). Requires module-aware parsing. |
| **Focused clinical policy** | Single-question, evidence-table-heavy | Addresses one clinical question with exhaustive evidence review. Heavy on comparative effectiveness narrative, lower computability. |

**Implication for cpg-ingester:** The extraction pipeline needs to detect the archetype early (from front matter and layout) and select the appropriate parsing strategy. A module-based guide needs module boundary detection; a journal article needs two-column layout handling.

### What lives in the back half

The sections beyond the main recommendations contain content critical for both extraction and care plan generation:

- **Pharmacology detail** — Dosing tables, titration schedules, drug interactions, and contraindications live deep in appendices, not in the recommendation text. These are often the most directly computable content in the entire document.
- **Evidence tables** — Structured GRADE assessments (Summary of Findings tables) cataloging every study with design, sample size, outcomes, and quality ratings. One guideline has 85+ supplementary SoF tables.
- **Monitoring schedules** — Detailed frequency tables indexed by disease stage, treatment type, and comorbidity. These are near-DMN-ready.
- **Implementation tools** — Audit criteria, performance indicators, quality measures, and workflow checklists.
- **Special populations** — Recommendations that modify earlier guidance for specific groups (elderly, pregnant, ethnic subgroups) appear in later sections and reference earlier recommendations.
- **Patient-facing content** — Shared decision-making scripts, patient information sections, educational materials.

**Recommendation detail evolves through the document in a clear pattern:**

1. **Front matter (~first 10%):** Algorithm flowcharts + recommendation summary table with one-line statements
2. **Early body (~10-25%):** Screening, diagnosis, risk assessment with moderate-length discussions
3. **Mid body (~25-55%):** Pharmacotherapy recommendations with extensive evidence narratives — clinical decision complexity peaks here. Drug selection requires evaluating ~10 patient factors simultaneously.
4. **Later body (~45-75%):** Subpopulation-specific modifier recommendations that layer on top of the general pathway. Later recommendations explicitly reference earlier ones.
5. **Appendices (~last 25%):** Pharmacotherapy reference tables, abbreviations, methodology, references

**Recommendation interdependence increases toward the end.** Early recommendations are relatively standalone; later ones are patches, overrides, or extensions of earlier ones. An extraction system treating each recommendation as independent will miss these dependency relationships.

**Stopping at the recommendation summary table captures less than 20% of actionable content.** The detailed discussions reveal 5-15 branching factors per recommendation that the one-liner summary does not expose.

**The appendix pharmacotherapy tables are the highest-value extraction target.** Structured drug class comparisons across 8+ clinical dimensions (efficacy, safety, organ-specific effects, weight, contraindications, dosing) are essentially pre-built decision tables waiting for DMN encoding.

**Abbreviation tables define the controlled vocabulary** used throughout the document. Without them, recommendation texts containing acronyms are ambiguous. These should be parsed first.

**Update history/changelog sections are critical metadata** that timestamps each recommendation's evidence review date, distinguishes evidence-reviewed changes from administrative ones, and identifies removed/superseded sections.

---

## 2. Recommendation Formatting

Three distinct presentation patterns emerge across CPGs:

**Pattern A — Boxed/highlighted recommendations with inline grade.** Recommendations appear in visually distinct containers (shaded boxes, colored headers) with the evidence grade stated immediately after. Easy to scan and separate from discussion text.

**Pattern B — Numbered recommendations with parenthetical grades.** Recommendations numbered sequentially within prose, grade in parentheses at the end. Common in journal-article-format CPGs where visual formatting is constrained.

**Pattern C — Hierarchically numbered with verb-implied strength.** Recommendations use decimal numbering (e.g., 1.2.3) without explicit letter/number grades. Strength is conveyed through carefully chosen verbs: "offer" or "ensure" for strong, "consider" for conditional. Year tags (e.g., "[2019]") indicate when each recommendation was last updated.

### Grading systems

Five distinct systems were observed, but all share a **two-axis structure** — one axis for evidence certainty (how confident), another for recommendation strength (how strongly it applies):

| System | Strength axis | Evidence axis |
|---|---|---|
| GRADE | Strong for / Weak for / Weak against / Strong against | High / Moderate / Low / Very low |
| Class of Recommendation (COR) | Class 1 / 2a / 2b / 3 | Level A / B-R / B-NR / C-LD / C-EO |
| GRADE + COR hybrid | Combines both | Combined |
| Simplified | Strong / Conditional | High / Moderate / Low certainty |
| Verb-based (implicit) | "offer" / "consider" / no grade | Year tags only |

**The hedging vocabulary is consistent** across all systems:
- "Is recommended" / "We recommend" — strongest
- "Should" — strong
- "We suggest" / "May be reasonable" — conditional
- "Consider" — weakest actionable language
- "Clinical judgment" — explicit delegation to clinician

**Practice points** (expert consensus without systematic evidence review) appear in several guideline families and need a distinct metadata category: "expert consensus, ungraded."

### Implication for cpg-ingester

The extraction system needs a **normalized certainty schema** that maps all grading systems into a common representation:

```
{
  strength: "strong" | "conditional" | "consensus",
  evidence_quality: "high" | "moderate" | "low" | "very_low" | "ungraded",
  original_system: "GRADE" | "COR-LOE" | "verb-implied" | ...,
  original_grade: "1A" | "Strong for, moderate certainty" | ...
}
```

Additional metadata dimensions identified through validation:
- **"No recommendation"** is a distinct output type — formal "no recommendation for or against" statements need explicit capture, distinct from silence (no mention) and from conditional recommendations.
- **Recommendation provenance** — some guidelines track each recommendation's lifecycle status (Reviewed/Amended/New-added/Not-changed) relative to prior versions. Critical for version-aware extraction.
- **"Remarks" sections** — structured bulleted implementation context attached to individual recommendations, sitting between the recommendation and its evidence discussion.

This metadata must travel with every extracted recommendation.

---

## 3. Decision Logic Patterns

### The computability spectrum

Content falls into three tiers:

**Tier 1 — Directly computable (DMN-ready):**
- Numeric thresholds: FPG ≥126 mg/dL, HbA1c ≥6.5%, BP ≥140/90 mmHg
- Staging/classification grids: CKD stages combine GFR categories (G1-G5) with albuminuria categories (A1-A3)
- Risk scores with defined variables
- Red flag checklists: IF (symptom A OR symptom B) THEN urgent evaluation
- Step therapy rules: IF Step 1 not tolerated THEN alternative
- Dose adjustments by lab values: reduce dose when eGFR <45, discontinue when eGFR <30
- Monitoring frequency tables indexed by disease stage

**Tier 2 — Semi-computable (requires interpretation):**
- Conditional recommendations with GRADE qualifiers ("We suggest..." vs "We recommend...")
- Risk stratification requiring external calculators (Framingham, ASCVD)
- Multi-condition branching with 3-4 simultaneous preconditions (these are computable population applicability criteria — they belong in DMN as gating inputs, not in the vector store)
- Medication selection influenced by age, ethnicity, comorbidity profile

**Tier 3 — Inherently narrative (vector store):**
- Rationale and evidence summaries
- Shared decision-making guidance
- Implementation considerations (cost, feasibility)
- Clinical judgment gates ("Consider specialty consultation")
- Quality of life trade-offs
- Patient education content

### Computability by clinical domain

| Domain | Approximate Tier 1 content | Notes |
|---|---|---|
| Hypertension | ~50% | Clear thresholds, step therapy, drug selection rules |
| Diabetes (type 2) | ~45% | Diagnostic criteria, medication algorithms, monitoring |
| CKD | ~40% | Staging matrix, eGFR-based dosing, monitoring frequency |
| Acute coronary syndromes | ~35% | Risk scores, time windows, but complex branching |
| Heart failure | ~30% | Staging, LVEF classification, extensive nuance |
| Low back pain | ~30% | Red flags highly computable; treatment is shared decision-making |
| Obesity | ~25-35% | BMI/waist thresholds, staging, surgical candidacy, medication-weight tables |
| Acute pain | ~20% | Comparative effectiveness but few hard rules |
| Emergency medicine (focused) | ~15-20% | Single-question format, evidence-table-heavy, lower computability |
| Mental health | ~10-15% | Qualitative assessments, psychosocial interventions |

Note: computability varies significantly within a domain depending on guideline scope — a comprehensive institutional guideline has more Tier 1 content than a focused single-question clinical policy on the same topic.

**Implication:** Start with hypertension and diabetes for highest-yield DMN extraction. Use mental health guidelines primarily as vector store content.

### How decision logic is expressed

Three forms observed:

1. **Flowchart algorithms** — Formal decision diamonds with yes/no branches. One family uses standardized symbols (hexagons for decisions, rectangles for actions). Alternative text descriptions sometimes provided in appendices for accessibility.

2. **If-then prose** — The most common pattern. Conditions stated in natural language: "If blood pressure ≥140/90 mmHg..." These are often nested with bullet points. Key sub-patterns:
   - Threshold-based: IF value ≥ X THEN action
   - Risk-stratified: IF condition AND risk level THEN action
   - Conditional sequencing: IF first action unsuitable THEN alternative
   - Step-escalation: Step 1 → Step 2 → Step 3

3. **Tabular decision aids** — Treatment selection matrices, dosing tables, classification tables. Sidebar lookup tables (condition × red flags → evaluation) are already near-DMN format.

4. **Patient consent/shared-decision-making gates** — Flowcharts include "Patient agrees" / "Patient declines" branches that are not clinical decision points but shared-decision-making gates. These require BPMN human-task modeling distinct from clinical decision diamonds.

**Critical finding:** Most decision logic is embedded in prose, not formal structures. Even when flowchart algorithms exist, the detailed conditions and exceptions live in the recommendation text. Algorithms are high-level visual summaries, not complete executable specifications.

---

## 4. Table Patterns

Tables serve distinct functions:

- **Grading/classification tables** — Define the recommendation grading system itself
- **Drug/medication tables** — Drug classes, specific medications, dosage ranges (often in appendices)
- **Summary of Findings (SoF) tables** — Compare interventions using PICOM format; can be extremely numerous
- **Evidence tables** — Individual studies with design, sample size, outcomes, quality ratings
- **Recommendation summary tables** — All recommendations consolidated with metadata
- **Classification tables** — BP stages, CKD categories, HbA1c ranges
- **Monitoring frequency tables** — What to measure, how often, indexed by disease stage
- **Risk scoring tables** — Point-based calculations with categorical outputs

The most complex are SoF/evidence comparison tables following the structured PICOM framework. The most extraction-valuable are monitoring frequency tables (near-DMN format) and drug dosing tables.

---

## 5. Content Beyond Decisions

A substantial portion of every CPG is not directly translatable into decision logic:

- **Background/epidemiology** — Contextualizes but is not actionable
- **Measurement technique** — Procedural instructions (e.g., how to properly measure BP). Defines how input variables should be obtained, directly affecting decision threshold validity
- **Patient-centered care** — Shared decision-making, cultural/health equity considerations
- **Harms and adverse effects** — Side effect profiles, often narrative
- **Lifestyle modifications** — Dietary guidance (DASH diet, sodium limits), exercise prescriptions, weight management, alcohol limits, smoking cessation
- **Implementation guidance** — Quality measures, audit criteria, performance indicators
- **Research gaps** — Areas where evidence is insufficient
- **Qualifying statements** — "Not intended to define a standard of care" — the contract between guideline and clinician

**Key insight:** Non-decision content often contains critical context for correctly interpreting the decision logic. Measurement technique sections define how input variables should be obtained. Contraindication sections modify when recommendations should NOT be applied. These must be retrievable alongside the decisions they qualify.

---

## 6. Cross-References and Dependencies

Three patterns of cross-referencing observed:

**Pattern A — Intra-guideline sequential chains:** Recommendations within a single guideline build on each other. Risk assessment output feeds treatment initiation input. These can be modeled as linked DMN decision tables.

**Pattern B — Inter-guideline dependencies:** Guidelines explicitly reference other guidelines for co-occurring conditions. One diabetes guideline references 7 other guidelines. This creates a web of dependencies that single-guideline extraction cannot resolve.

**Pattern C — Hub-and-spoke routing:** One mental health guideline uses a "Master Chart" that routes patients to condition-specific modules based on presenting complaints. Each module is self-contained but references universal checks (e.g., suicide assessment from multiple entry points).

**Conditional chains can be deep:** screen → diagnostic test → confirm diagnosis → stage → assess comorbidities → select treatment → initiate therapy → monitor → reassess → escalate/maintain — up to 10 steps with branching at most of them.

### Overlapping and conflicting guidance

When multiple guidelines cover the same condition, they agree on direction but differ on specifics:

- **BP targets:** <140/90 (general), <130/80 (high risk), <120 systolic (intensive), <150/90 (age ≥80) — different guidelines, different populations
- **HbA1c targets:** <6.5%, <7.0%, ≤8.0% — varying by frailty, life expectancy, hypoglycemia risk
- **Drug class preference:** Varies by population studied and healthcare system context

These are not contradictions — they reflect different patient populations and evidence bases. But when a patient has CKD AND diabetes AND is over 60, which target applies?

**Subpopulation modifiers create layered decision trees.** Later CPG sections contain recommendation sets that modify the general treatment algorithm for specific patient subgroups (CKD, frailty, specific comorbidities). These are not standalone recommendations — they are patches/overrides to the base set. A patient matching multiple subpopulations needs multiple modifier sets applied in combination.

**Implication:** Extracted recommendations must carry source metadata. The extraction system should not reconcile conflicts — that is a clinical decision for acp-writer and the clinician. The vector store should enable retrieval of all relevant recommendations with their respective contexts.

---

## 7. Visual Content and Parsing Challenges

Seven categories of visual information carry clinical meaning that text extraction will miss:

1. **Flowchart algorithms** — Decision diamonds, branching paths, action boxes. Text extraction gets labels but loses flow structure.
2. **Color-coded risk matrices** — CKD staging uses a heat map where color IS the risk level.
3. **Scoring nomograms** — Analog computation requiring perpendicular-line drawing.
4. **Infographic summaries** — Effect sizes encoded as bar chart lengths, certainty as icons.
5. **ECG/imaging criteria** — Spatial relationships on a 12-lead ECG.
6. **Treatment pyramids** — Position encodes priority order (first-line at base, last resort at apex).
7. **Module-level icons** — Visual vocabulary for assessment, medication, referral, caution, "do not."

### Layout complexity by format

- **Journal articles** — Two-column, small font, dense. Content flows across columns and pages. Hardest for automated parsing.
- **Standalone institutional documents** — Single-column, generous spacing, consistent branding. Most parser-friendly.
- **Journal supplements** — Hybrid format with journal front matter before CPG content.

**Key parsing challenge:** The same semantic structure (a recommendation with its grade) looks completely different across formats — a colored box in one, an indented paragraph in another, a numbered item with verb-implied strength in a third.

---

## 8. Temporal Patterns

Five distinct temporal patterns identified:

| Pattern | Timescale | Example | FHIR/BPMN mapping |
|---|---|---|---|
| Acute time windows | Minutes to hours | ECG within 10 minutes; door-to-balloon ≤90 min | BPMN timer events |
| Treatment initiation | Days to weeks | Monitor potassium 2-4 weeks after starting ACEi | Scheduled ServiceRequests |
| Goal-based reassessment | Months | BP monthly until target, then every 3-6 months | BPMN conditional loops |
| Chronic monitoring | Annual+ | eGFR and albuminuria at least annually | Recurring ServiceRequests |
| Duration-based reclassification | Threshold-triggered | Acute pain (<4wk) → subacute (4-12wk) → chronic (≥12wk) | New decision points |

**The under-specification problem is pervasive.** Many guidelines say "follow-up" or "reassess" without specifying an interval. "Close follow-up" appears frequently with no definition. The care plan system needs defaults when guidelines are silent — surfaced as system-generated rather than guideline-specified.

---

## 9. Care Plan Goals

### Goal measurability spectrum

**Highly measurable:** BP <140/90, HbA1c <7.0%, LDL <70 mg/dL, eGFR decline <5/year → FHIR Goal.target with quantity

**Conditionally measurable:** Targets that depend on patient factors (HbA1c "may be relaxed" for frailty) → FHIR Goal with target AND rationale

**Functional:** Pain reduction, functional improvement, symptom improvement → Goal with coded outcome measure but patient-specific target

**Process:** Attend education program, complete cardiac rehab, self-monitor BP → Better modeled as CarePlan activities than Goals

**Psychosocial:** "Reduce stress," social reintegration, quality of life → Narrative only, resist numeric encoding

---

## 10. Implications for System Design

### For cpg-ingester

1. **Dual-track extraction:** Route Tier 1 content to DMN, Tier 3 to vector store, flag Tier 2 for human review.
2. **Read the FULL document.** Dosing tables, monitoring schedules, and contraindications live in appendices, not introductions.
3. **Normalize certainty grades** across the five grading systems into a common schema.
4. **Preserve cross-references** as typed links (intra-guideline, inter-guideline, routing) — don't resolve inline.
5. **Handle flowcharts and tables** as first-class extraction targets — sidebar lookup tables are near-DMN format.
6. **Classify content by type** during extraction: treatment, diagnostic, monitoring, lifestyle, educational, referral.
7. **Ambiguity flagging:** When "consider" appears without a threshold, flag for human review.
8. **Detect the format archetype** (institutional, journal article, multi-module, focused policy) early and select the appropriate parsing strategy.
9. **Parse grading definitions and glossaries first** — each CPG re-defines its grading vocabulary inline. Glossaries contain computable classification thresholds.
10. **Support incremental re-extraction** for living guidelines that receive continuous updates rather than periodic version releases.

### For acp-writer

1. **Layered clinician UI:** Recommendation action as primary display; expandable panels for evidence strength, harms, contraindications, monitoring, alternatives, applicability.
2. **Multi-table DMN evaluation:** Patient's full clinical profile evaluated across multiple decision tables. Conflicts between tables surfaced to clinician, not silently resolved.
3. **Narrative activities are unavoidable:** 20-30% of recommendations will be narrative CarePlan activities (lifestyle, education, psychosocial). Design for this.
4. **Goal individualization:** Most targets should be adjustable, with the guideline-specified target as the default and clinician override documented.
5. **Temporal orchestration:** Generate ServiceRequests at guideline-specified intervals; apply defaults when guidelines are silent; model escalation loops.
6. **The "clinical judgment" boundary:** Every guideline preserves space for clinician override. The system must never present outputs as definitive. Every recommendation must carry its uncertainty.

### For the recommendation contract (Phase 3.0)

The vector store content must carry structured metadata alongside narrative text:

- **Source metadata:** Guideline identifier, publication year, evidence review date
- **Certainty metadata:** Normalized strength and evidence quality
- **Scope notes:** Non-computable caveats about the recommendation's applicability — study population characteristics, trial exclusion criteria, settings where evidence may not generalize. (Note: computable applicability criteria — diagnosis codes, age ranges, lab thresholds, comorbidity gates — should be extracted as DMN decision inputs, not stored as recommendation metadata.)
- **Recommendation type:** Treatment, diagnostic, monitoring, lifestyle, educational, referral
- **Cross-reference links:** Typed links to related recommendations
- **Context category:** Rationale, contraindication, monitoring requirement, benefit/harm, implementation note

Without this metadata, the vector store becomes a bag of text snippets that acp-writer cannot reliably filter, rank, or present with appropriate context.
