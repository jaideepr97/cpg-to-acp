"""LLM-assisted query plan synthesis for clinical QA.

Translates natural language questions into structured query plans
over the extraction and temporal primitives. Plans are validated
against a JSON schema before execution.
"""

import json
import logging
from datetime import date
from typing import Any

import mlflow

from acp_writer.tools.ips_serializer import serialize_ips

logger = logging.getLogger(__name__)

QUERY_PLAN_SCHEMA = {
    "type": "object",
    "required": ["function", "params"],
    "properties": {
        "function": {
            "type": "string",
            "enum": [
                "latest_value",
                "has_condition",
                "has_medication",
                "has_allergy",
                "has_procedure",
                "has_family_history",
                "patient_age",
                "compute_bmi",
                "observation_count",
                "observations_in_window",
                "consecutive_above",
                "rate_of_change",
                "cross_resource_temporal",
                "trend_declining",
            ],
        },
        "params": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "system|code token, e.g. http://loinc.org|8480-6"},
                "duration": {"type": "string", "description": "ISO 8601 duration, e.g. P3M"},
                "threshold": {"type": "number"},
                "comparator": {"type": "string", "enum": ["ge", "gt", "le", "lt", "eq"]},
                "anchor_code": {"type": "string"},
                "target_code": {"type": "string"},
                "window": {"type": "string"},
                "target_date": {"type": "string"},
            },
        },
    },
}

SYSTEM_PROMPT = """You are a clinical data query planner. Given a clinical question about a patient,
generate a JSON query plan that specifies which extraction function to call and with what parameters.

Available functions:
- latest_value: Get the most recent observation value. Params: code (system|code token)
- has_condition: Check if patient has an active condition. Params: code (SNOMED system|code)
- has_medication: Check if patient is on a medication. Params: code (RxNorm system|code)
- has_allergy: Check if patient has an allergy. Params: code (SNOMED system|code)
- has_procedure: Check if patient has had a procedure. Params: code (SNOMED system|code)
- has_family_history: Check for family history of a condition. Params: code (SNOMED system|code)
- patient_age: Compute patient's age. No params needed.
- compute_bmi: Compute BMI from height and weight. No params needed.
- observation_count: Count observations matching criteria in a time window. Params: code, duration, threshold (optional), comparator (optional)
- observations_in_window: Get all observations in a time window. Params: code, duration
- consecutive_above: Count consecutive readings above threshold from most recent. Params: code, threshold
- rate_of_change: Compute slope of values over time. Params: code, duration
- cross_resource_temporal: Check if target observation exists within window of anchor medication start. Params: anchor_code, target_code, window
- trend_declining: Check if most recent reading is lower than previous. Params: code

Common code tokens:
- Systolic BP: http://loinc.org|8480-6
- Diastolic BP: http://loinc.org|8462-4
- HbA1c: http://loinc.org|4548-4
- eGFR: http://loinc.org|33914-3
- Creatinine: http://loinc.org|2160-0
- Potassium: http://loinc.org|2823-3
- Fasting glucose: http://loinc.org|1558-6
- LDL: http://loinc.org|2089-1
- Hypertension: http://snomed.info/sct|59621000
- Type 2 diabetes: http://snomed.info/sct|44054006
- CKD: http://snomed.info/sct|709044004

Duration format: P followed by number and unit (Y=years, M=months, W=weeks, D=days). E.g. P3M = 3 months.

The JSON object MUST have exactly two keys: "function" and "params".
Example: {"function": "latest_value", "params": {"code": "http://loinc.org|4548-4"}}
Example: {"function": "patient_age", "params": {}}

Respond with ONLY a valid JSON object. No markdown, no explanation."""


def validate_plan(plan: dict) -> list[str]:
    """Validate a query plan against the schema. Returns a list of errors."""
    errors = []

    if not isinstance(plan, dict):
        return ["Plan must be a JSON object"]

    if "function" not in plan:
        errors.append("Missing required field: function")
    elif plan["function"] not in QUERY_PLAN_SCHEMA["properties"]["function"]["enum"]:
        errors.append(f"Unknown function: {plan['function']}")

    if "parameters" in plan and "params" not in plan:
        plan["params"] = plan.pop("parameters")

    if "params" not in plan:
        errors.append("Missing required field: params")
    elif not isinstance(plan["params"], dict):
        errors.append("params must be an object")

    return errors


@mlflow.trace(name="qa_generate_query_plan")
def generate_query_plan(
    question: str,
    condensed_ips: str,
    reference_date: date,
    llm_client: Any,
) -> dict | None:
    """Use an LLM to generate a query plan from a natural language question.

    Returns the validated plan dict, or None if generation/validation fails.
    """
    user_prompt = (
        f"Patient data (condensed):\n{condensed_ips}\n\n"
        f"Reference date: {reference_date.isoformat()}\n\n"
        f"Question: {question}\n\n"
        f"Generate a JSON query plan to answer this question."
    )

    try:
        response = llm_client.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ])

        content = response.content if hasattr(response, "content") else str(response)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        plan = json.loads(content)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Failed to parse LLM query plan: %s", exc)
        return None

    errors = validate_plan(plan)
    if errors:
        logger.warning("Query plan validation failed: %s", errors)
        return None

    return plan
