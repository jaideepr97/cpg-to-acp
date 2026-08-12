"""LLM agent for complex clinical QA.

Uses LangGraph's prebuilt ReAct agent with clinical extraction tools.
The agent iteratively queries patient data and applies clinical
reasoning to answer questions the concept resolver can't handle.
"""

import json
import logging
from datetime import date
from typing import Any

import mlflow
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field

from acp_writer.tools.ips_extractor import (
    extract_allergy,
    extract_condition,
    extract_medication,
    extract_observation,
    extract_patient_age,
)
from acp_writer.tools.ips_serializer import serialize_ips
from acp_writer.tools.temporal_index import build_temporal_index
from acp_writer.tools.temporal_queries import (
    observation_count,
    rate_of_change,
)

logger = logging.getLogger(__name__)

_AGENT_SYSTEM_PROMPT = """You are a clinical data analyst answering factual questions about a patient
using their FHIR IPS (International Patient Summary) data. You have tools to query the patient's
observations, conditions, medications, and allergies.

You also receive a condensed text summary of the patient's data. Use BOTH the summary AND the tools:
- Use the summary to understand the full clinical picture and identify relevant data
- Use tools to extract precise values when needed for calculations or comparisons
- For questions about the summary text itself (display names, free text), answer directly from the summary

Clinical reasoning guidelines:
- Apply standard clinical knowledge: drug classes, treatment targets, risk scores, contraindications
- For drug class questions, reason about whether specific medications belong to the asked-about class
- For treatment target questions, apply standard guidelines (e.g., BP <130/80 for diabetics, HbA1c <7%, LDL <70 for secondary prevention)
- For risk scoring, explain your calculation step by step
- When data is genuinely insufficient or ambiguous (e.g., conflicting values), say so clearly

Response format — respond with a JSON object:
{"answer": <value>, "provenance": [<fhir_references>], "insufficient_data": false, "reasoning": "brief explanation"}

For boolean questions, answer is true or false.
For numeric questions, answer is the number.
For "insufficient data", use: {"answer": null, "provenance": [], "insufficient_data": true, "reasoning": "why"}"""

_BUNDLE_HOLDER: dict[str, Any] = {}
_INDEX_HOLDER: dict[str, Any] = {}
_REF_DATE_HOLDER: dict[str, Any] = {}


@tool
def lookup_observation(system: str, code: str) -> str:
    """Look up the most recent observation value by terminology system and code.

    Use this to get specific lab values, vital signs, or other measurements.

    Args:
        system: The terminology system URL (e.g., "http://loinc.org")
        code: The code within that system (e.g., "8480-6" for systolic BP)

    Common codes:
        Systolic BP: system="http://loinc.org", code="8480-6"
        Diastolic BP: system="http://loinc.org", code="8462-4"
        HbA1c: system="http://loinc.org", code="4548-4"
        eGFR: system="http://loinc.org", code="33914-3"
        Creatinine: system="http://loinc.org", code="2160-0"
        Potassium: system="http://loinc.org", code="2823-3"
        LDL: system="http://loinc.org", code="2089-1"
        BNP: system="http://loinc.org", code="30934-4"
        EF: system="http://loinc.org", code="10230-1"
        Heart rate: system="http://loinc.org", code="8867-4"
        TSH: system="http://loinc.org", code="3016-3"

    Returns JSON with: found, value, unit, date, fhir_reference
    """
    bundle = _BUNDLE_HOLDER.get("bundle", {})
    result = extract_observation(bundle, system, code)
    return json.dumps(result.to_dict())


@tool
def check_condition(system: str, code: str) -> str:
    """Check if the patient has an active condition.

    Args:
        system: Usually "http://snomed.info/sct" for SNOMED or "http://hl7.org/fhir/sid/icd-10-cm" for ICD-10
        code: The condition code (e.g., "44054006" for type 2 diabetes)

    Common SNOMED codes:
        Hypertension: 59621000
        Type 2 diabetes: 44054006
        CKD: 709044004
        Heart failure: 84114007 (or 441530006 for HFrEF)
        Atrial fibrillation: 49436004
        Obesity: 414916001
        Hyperlipidemia: 55822004
        COPD: 13645005
        Osteoarthritis: 396275006

    Returns JSON with: found (bool), value (true/false)
    """
    bundle = _BUNDLE_HOLDER.get("bundle", {})
    result = extract_condition(bundle, system, code)
    return json.dumps(result.to_dict())


@tool
def check_medication(system: str, code: str) -> str:
    """Check if the patient is on a specific medication.

    Args:
        system: Usually "http://www.nlm.nih.gov/research/umls/rxnorm"
        code: The RxNorm code

    Returns JSON with: found (bool)
    """
    bundle = _BUNDLE_HOLDER.get("bundle", {})
    result = extract_medication(bundle, system, code)
    return json.dumps(result.to_dict())


@tool
def check_allergy(system: str, code: str) -> str:
    """Check if the patient has an allergy.

    Args:
        system: Usually "http://snomed.info/sct"
        code: The allergen SNOMED code

    Returns JSON with: found (bool)
    """
    bundle = _BUNDLE_HOLDER.get("bundle", {})
    result = extract_allergy(bundle, system, code)
    return json.dumps(result.to_dict())


@tool
def get_patient_age() -> str:
    """Get the patient's current age in years.

    Returns JSON with: found (bool), value (age in years)
    """
    bundle = _BUNDLE_HOLDER.get("bundle", {})
    ref_date = _REF_DATE_HOLDER.get("date", date.today())
    result = extract_patient_age(bundle, ref_date)
    return json.dumps(result.to_dict())


@tool
def count_observations_in_window(code_token: str, duration: str,
                                  threshold: float | None = None,
                                  comparator: str | None = None) -> str:
    """Count observations matching criteria in a time window.

    Args:
        code_token: system|code (e.g., "http://loinc.org|8480-6")
        duration: ISO 8601 duration (e.g., "P3M" for 3 months)
        threshold: Optional numeric threshold to filter by
        comparator: Optional comparator: "ge", "gt", "le", "lt", "eq"

    Returns JSON with: found, value (count), provenance
    """
    index = _INDEX_HOLDER.get("index")
    ref_date = _REF_DATE_HOLDER.get("date", date.today())
    if not index:
        return json.dumps({"error": "No temporal index available"})
    result = observation_count(index, code_token, duration, ref_date, threshold, comparator)
    return json.dumps({"found": result.found, "value": result.value,
                      "provenance": result.provenance,
                      "insufficient_data": result.insufficient_data})


@tool
def get_observation_trend(code_token: str, duration: str) -> str:
    """Compute the rate of change of an observation over time.

    Args:
        code_token: system|code (e.g., "http://loinc.org|33914-3" for eGFR)
        duration: Time window (e.g., "P1Y" for 1 year)

    Returns slope normalized per year. Negative = declining.
    """
    index = _INDEX_HOLDER.get("index")
    ref_date = _REF_DATE_HOLDER.get("date", date.today())
    if not index:
        return json.dumps({"error": "No temporal index available"})
    result = rate_of_change(index, code_token, duration, ref_date)
    return json.dumps({"found": result.found, "value": result.value,
                      "provenance": result.provenance,
                      "insufficient_data": result.insufficient_data})


_ALL_TOOLS = [
    lookup_observation, check_condition, check_medication,
    check_allergy, get_patient_age, count_observations_in_window,
    get_observation_trend,
]


class QAResponse(BaseModel):
    """Structured response from the QA agent."""
    answer: Any = Field(description="The answer value (number, boolean, string, or null)")
    provenance: list[str] = Field(default_factory=list, description="FHIR references used")
    insufficient_data: bool = Field(default=False, description="True if data is insufficient to answer")
    reasoning: str = Field(default="", description="Brief explanation of the answer")


@mlflow.trace(name="qa_agent_answer")
def agent_answer(
    question: str,
    bundle: dict,
    reference_date: date,
    llm_client: Any,
    max_iterations: int = 10,
) -> dict:
    """Run the ReAct QA agent to answer a clinical question.

    Returns: {"answer": value, "provenance": [...], "insufficient_data": bool}
    """
    _BUNDLE_HOLDER["bundle"] = bundle
    _INDEX_HOLDER["index"] = build_temporal_index(bundle)
    _REF_DATE_HOLDER["date"] = reference_date

    condensed = serialize_ips(bundle)

    try:
        agent = create_react_agent(
            llm_client,
            _ALL_TOOLS,
            prompt=SystemMessage(content=_AGENT_SYSTEM_PROMPT),
        )

        result = agent.invoke(
            {"messages": [HumanMessage(content=(
                f"Patient summary:\n{condensed}\n\n"
                f"Reference date: {reference_date.isoformat()}\n\n"
                f"Question: {question}\n\n"
                f"Use the tools and the patient summary above to answer. "
                f"Respond with a JSON object containing answer, provenance, insufficient_data, and reasoning."
            ))]},
            {"recursion_limit": max_iterations * 2},
        )

        last_message = result["messages"][-1]
        return _parse_agent_response(last_message)

    except Exception as exc:
        logger.warning("QA agent failed: %s", exc)
        return {"answer": None, "provenance": [], "insufficient_data": True,
                "error": str(exc)}
    finally:
        _BUNDLE_HOLDER.clear()
        _INDEX_HOLDER.clear()
        _REF_DATE_HOLDER.clear()


def _parse_agent_response(message: Any) -> dict:
    """Parse the agent's final message into a structured answer."""
    content = message.content if hasattr(message, "content") else str(message)
    content = content.strip()

    if "INSUFFICIENT_DATA" in content.upper():
        return {"answer": None, "provenance": [], "insufficient_data": True}

    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    try:
        parsed = json.loads(content)
        return {
            "answer": parsed.get("answer"),
            "provenance": parsed.get("provenance", []),
            "insufficient_data": parsed.get("insufficient_data", False),
        }
    except json.JSONDecodeError:
        if content.lower() in ("true", "false"):
            return {"answer": content.lower() == "true", "provenance": [], "insufficient_data": False}
        try:
            return {"answer": float(content), "provenance": [], "insufficient_data": False}
        except ValueError:
            return {"answer": content, "provenance": [], "insufficient_data": False}
