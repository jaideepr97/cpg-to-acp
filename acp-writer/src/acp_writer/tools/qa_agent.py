"""LLM agent for complex clinical QA.

A LangGraph agent with access to the extraction functions as tools.
Used as the final fallback when concept resolver and query plan
synthesis can't answer a question.
"""

import json
import logging
from datetime import date
from typing import Any

import mlflow
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from acp_writer.tools.ips_extractor import (
    ExtractionResult,
    extract_allergy,
    extract_condition,
    extract_diagnostic_report,
    extract_family_history,
    extract_medication,
    extract_observation,
    extract_patient_age,
    extract_procedure,
)
from acp_writer.tools.ips_serializer import serialize_ips
from acp_writer.tools.temporal_index import TemporalIndex, build_temporal_index
from acp_writer.tools.temporal_queries import (
    consecutive_above,
    cross_resource_temporal,
    observation_count,
    observations_in_window,
    rate_of_change,
)

logger = logging.getLogger(__name__)

_AGENT_SYSTEM_PROMPT = """You are a clinical data extraction agent. You answer factual questions about
a patient by querying their FHIR IPS (International Patient Summary) data using the tools provided.

Rules:
1. Use the tools to find data. Do not guess or assume values.
2. If the data needed to answer the question is not available, respond with: INSUFFICIENT_DATA
3. For numeric answers, return just the number (e.g., "142" not "142 mmHg").
4. For boolean answers, return "true" or "false".
5. For coded answers, return the code value.
6. Always cite the FHIR references of resources you used.
7. Be precise. Clinical data extraction errors can affect patient care.

Respond with a JSON object:
{"answer": <value>, "provenance": [<fhir_references>], "insufficient_data": false}
or
{"answer": null, "provenance": [], "insufficient_data": true, "reason": "..."}"""

_BUNDLE_HOLDER: dict[str, Any] = {}
_INDEX_HOLDER: dict[str, TemporalIndex] = {}
_REF_DATE_HOLDER: dict[str, date] = {}


def _make_tools():
    """Create LangChain tool wrappers around the extraction functions."""

    @tool
    def lookup_observation(system: str, code: str) -> str:
        """Look up the most recent observation by terminology system and code.
        Example: system="http://loinc.org", code="8480-6" for systolic BP."""
        bundle = _BUNDLE_HOLDER.get("bundle", {})
        result = extract_observation(bundle, system, code)
        return json.dumps(result.to_dict())

    @tool
    def check_condition(system: str, code: str) -> str:
        """Check if the patient has an active condition by SNOMED code.
        Example: system="http://snomed.info/sct", code="44054006" for diabetes."""
        bundle = _BUNDLE_HOLDER.get("bundle", {})
        result = extract_condition(bundle, system, code)
        return json.dumps(result.to_dict())

    @tool
    def check_medication(system: str, code: str) -> str:
        """Check if the patient is on a medication by RxNorm code."""
        bundle = _BUNDLE_HOLDER.get("bundle", {})
        result = extract_medication(bundle, system, code)
        return json.dumps(result.to_dict())

    @tool
    def check_allergy(system: str, code: str) -> str:
        """Check if the patient has an allergy by SNOMED code."""
        bundle = _BUNDLE_HOLDER.get("bundle", {})
        result = extract_allergy(bundle, system, code)
        return json.dumps(result.to_dict())

    @tool
    def get_patient_age() -> str:
        """Get the patient's age in years."""
        bundle = _BUNDLE_HOLDER.get("bundle", {})
        ref_date = _REF_DATE_HOLDER.get("date", date.today())
        result = extract_patient_age(bundle, ref_date)
        return json.dumps(result.to_dict())

    @tool
    def count_observations(code_token: str, duration: str,
                           threshold: float = None, comparator: str = None) -> str:
        """Count observations matching criteria in a time window.
        code_token: system|code (e.g. http://loinc.org|8480-6)
        duration: ISO 8601 (e.g. P3M)
        threshold/comparator: optional filter (e.g. 140, "ge")"""
        index = _INDEX_HOLDER.get("index")
        ref_date = _REF_DATE_HOLDER.get("date", date.today())
        if not index:
            return json.dumps({"error": "No temporal index available"})
        result = observation_count(index, code_token, duration, ref_date, threshold, comparator)
        return json.dumps({"found": result.found, "value": result.value,
                          "provenance": result.provenance,
                          "insufficient_data": result.insufficient_data})

    @tool
    def get_rate_of_change(code_token: str, duration: str) -> str:
        """Compute the rate of change of an observation over time.
        Returns slope normalized per year."""
        index = _INDEX_HOLDER.get("index")
        ref_date = _REF_DATE_HOLDER.get("date", date.today())
        if not index:
            return json.dumps({"error": "No temporal index available"})
        result = rate_of_change(index, code_token, duration, ref_date)
        return json.dumps({"found": result.found, "value": result.value,
                          "provenance": result.provenance,
                          "insufficient_data": result.insufficient_data})

    return [
        lookup_observation, check_condition, check_medication,
        check_allergy, get_patient_age, count_observations,
        get_rate_of_change,
    ]


@mlflow.trace(name="qa_agent_answer")
def agent_answer(
    question: str,
    bundle: dict,
    reference_date: date,
    llm_client: Any,
    max_iterations: int = 5,
) -> dict:
    """Run the QA agent to answer a clinical question.

    Returns: {"answer": value, "provenance": [...], "insufficient_data": bool}
    """
    _BUNDLE_HOLDER["bundle"] = bundle
    _INDEX_HOLDER["index"] = build_temporal_index(bundle)
    _REF_DATE_HOLDER["date"] = reference_date

    condensed = serialize_ips(bundle)
    tools = _make_tools()
    tool_map = {t.name: t for t in tools}

    llm_with_tools = llm_client.bind_tools(tools)

    messages = [
        SystemMessage(content=_AGENT_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Patient summary:\n{condensed}\n\n"
            f"Reference date: {reference_date.isoformat()}\n\n"
            f"Question: {question}"
        )),
    ]

    try:
        for _ in range(max_iterations):
            response = llm_with_tools.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                return _parse_agent_response(response)

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                if tool_name in tool_map:
                    result = tool_map[tool_name].invoke(tool_args)
                    from langchain_core.messages import ToolMessage
                    messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))
                else:
                    from langchain_core.messages import ToolMessage
                    messages.append(ToolMessage(
                        content=json.dumps({"error": f"Unknown tool: {tool_name}"}),
                        tool_call_id=tool_call["id"],
                    ))

    except Exception as exc:
        logger.warning("QA agent failed: %s", exc)
        return {"answer": None, "provenance": [], "insufficient_data": True,
                "error": str(exc)}
    finally:
        _BUNDLE_HOLDER.clear()
        _INDEX_HOLDER.clear()
        _REF_DATE_HOLDER.clear()

    return {"answer": None, "provenance": [], "insufficient_data": True,
            "error": "Max iterations reached"}


def _parse_agent_response(response: AIMessage) -> dict:
    """Parse the agent's final response into a structured answer."""
    content = response.content if hasattr(response, "content") else str(response)
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
        return {"answer": content, "provenance": [], "insufficient_data": False}
