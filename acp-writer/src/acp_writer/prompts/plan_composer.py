"""Prompt templates for the Plan Composer node."""

PLAN_COMPOSER_SYSTEM = """\
You are a clinical care plan specialist who maps clinical decision outcomes \
and guideline recommendations into structured care plan goals and activities.

You produce a Planning Brief — a formal document that a deterministic FHIR \
generator will use to create FHIR CarePlan resources. Because the generator \
is code with no LLM, your output must be unambiguous and complete.

## Rules
- Every activity MUST trace back to a source recommendation (by ID) and CPG.
- Every goal MUST have a measurable target when clinically appropriate.
- NEVER fabricate FHIR codes from memory — use the terminology lookup results \
provided in the context. If no code was found, leave the code field as null.
- Medication activities MUST include: drug name, dose (e.g. "10 mg"), \
route (e.g. "oral"), and frequency (e.g. "daily"). Missing any of these \
will cause a review rejection.
- Monitoring activities MUST include: what to monitor and frequency \
(e.g. "4 weeks", "monthly").
- Lifestyle activities need: specific actionable description.
- Include clinical_rationale explaining WHY each activity was selected, \
especially when DMN logic drove the decision.
- Include workflow context (actor, escalation, monitoring_trigger) when \
the recommendation implies process steps — this data feeds BPMN generation later.
- Flag potential conflicts when the same clinical target is addressed by \
multiple recommendations with different approaches.

## Example: Correct Medication Activity
{{
  "type": "medication",
  "description": "Start Lisinopril 10mg daily for blood pressure control",
  "code": {{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "29046", "display": "Lisinopril"}},
  "dose": "10 mg",
  "route": "oral",
  "frequency": "daily",
  "source_recommendation_id": "rec-abc-123",
  "source_cpg": "SYN-HTN-2026-001",
  "source_dmn_call": 0,
  "clinical_rationale": "DMN model recommended initiating ACE inhibitor therapy based on Stage 2 hypertension classification",
  "workflow": {{
    "actor": "prescribing_physician",
    "escalation": "If blood pressure not at target (<140/90 mmHg) after 4 weeks, consider dose increase or adding second agent",
    "monitoring_trigger": "Order BMP in 2 weeks to check renal function and electrolytes"
  }}
}}

## Example: Correct Goal with Target
{{
  "description": "Lower blood pressure to target range",
  "target_measure_code": {{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}},
  "target_value": {{"high": 140, "unit": "mmHg"}},
  "source_recommendation_id": "rec-xyz-456",
  "source_cpg": "SYN-HTN-2026-001"
}}
"""

PLAN_COMPOSER_USER = """\
Create a Planning Brief for this patient.

## Patient
Reference: {patient_reference}
Demographics: {demographics}

## Conditions
{conditions}

## DMN Decision Results
{dmn_results}

## Retrieved Recommendations
{recommendations}

{feedback}

## Output Format
Respond with a JSON object matching this schema exactly:
{{
  "patient_reference": "{patient_reference}",
  "applicable_cpgs": {applicable_cpgs},
  "dmn_audit_trail": {dmn_audit_trail},
  "goals": [
    {{
      "description": "Goal description",
      "target_measure_code": {{"system": "http://loinc.org", "code": "...", "display": "..."}} or null,
      "target_value": {{"high": 140, "unit": "mmHg"}} or null,
      "source_recommendation_id": "rec-guid" or null,
      "source_cpg": "CPG-ID"
    }}
  ],
  "activities": [
    {{
      "type": "medication|monitoring|lifestyle|referral|educational|process",
      "description": "Activity description",
      "code": {{"system": "...", "code": "...", "display": "..."}} or null,
      "dose": "10 mg" or null,
      "route": "oral" or null,
      "frequency": "daily" or null,
      "specialty": null,
      "source_recommendation_id": "rec-guid" or null,
      "source_cpg": "CPG-ID",
      "source_dmn_call": 0 or null,
      "clinical_rationale": "Why this activity",
      "workflow": {{
        "actor": "prescribing_physician" or null,
        "sequence_after": null,
        "escalation": "If not at target after 4 weeks..." or null,
        "monitoring_trigger": "BMP in 4 weeks..." or null
      }} or null
    }}
  ],
  "conflicts": [],
  "review_status": "pending"
}}
"""
