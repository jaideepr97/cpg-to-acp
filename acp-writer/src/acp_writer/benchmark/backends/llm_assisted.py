"""LLM-assisted benchmark backend — concept resolver + LLM query plan + agent fallback.

Implements the full layered resolution strategy:
1. Structured intent (if provided)
2. Concept resolver (deterministic)
3. LLM query plan synthesis (C2)
4. LLM agent with tools (C3)
"""

import logging
import os
from datetime import date
from typing import Any

from acp_writer.benchmark.backends.current import CurrentImplementationBackend
from acp_writer.benchmark.models import QAAnswer
from acp_writer.tools.concept_resolver import resolve as resolve_concept
from acp_writer.tools.ips_serializer import serialize_ips
from acp_writer.tools.query_planner import generate_query_plan

logger = logging.getLogger(__name__)


class LLMAssistedBackend(CurrentImplementationBackend):
    """Extends CurrentImplementationBackend with LLM-assisted resolution layers."""

    name: str = "llm-assisted"

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            base_url = os.environ.get("LLM_BASE_URL", os.environ.get("LITELLM_URL", "http://localhost:4000"))
            model = os.environ.get("LLM_MODEL", "default")
            api_key = os.environ.get("LLM_API_KEY", "not-set")
            self._llm = ChatOpenAI(
                base_url=base_url,
                model=model,
                api_key=api_key,
                temperature=0,
                max_retries=3,
                request_timeout=60,
            )
        return self._llm

    def answer(
        self,
        question: str,
        bundle: dict[str, Any],
        reference_date: date,
        structured_intent: dict[str, Any] | None = None,
    ) -> QAAnswer:
        if structured_intent is not None:
            return super().answer(question, bundle, reference_date, structured_intent)

        resolved = resolve_concept(question)
        if resolved:
            return self._execute_resolved(resolved, bundle, reference_date)

        return self._llm_resolve(question, bundle, reference_date)

    def _llm_resolve(
        self, question: str, bundle: dict, reference_date: date,
    ) -> QAAnswer:
        """Try LLM query plan synthesis, falling back to agent."""
        condensed = serialize_ips(bundle)
        llm = self._get_llm()

        plan = generate_query_plan(question, condensed, reference_date, llm)
        if plan:
            result = super().answer(
                question, bundle, reference_date,
                structured_intent=plan,
            )
            if not result.insufficient_data or not result.error:
                return result

        from acp_writer.tools.qa_agent import agent_answer

        agent_result = agent_answer(question, bundle, reference_date, llm)
        return QAAnswer(
            value=agent_result.get("answer"),
            kind=self._infer_kind(agent_result.get("answer")),
            provenance=agent_result.get("provenance", []),
            insufficient_data=agent_result.get("insufficient_data", False),
            error=agent_result.get("error"),
        )

    @staticmethod
    def _infer_kind(value: Any) -> str:
        if value is None:
            return "insufficient_data"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        return "code"
