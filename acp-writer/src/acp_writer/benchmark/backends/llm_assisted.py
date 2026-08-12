"""LLM-assisted benchmark backend — concept resolver + pipeline + agent fallback.

Layered resolution with fall-through semantics:
1. Structured intent (if provided) → deterministic execution
2. Concept resolver (deterministic) → positive/insufficient short-circuit;
   negative booleans fall through to LLM (not definitive without pipeline)
3. LLM query plan synthesis → execute plan
4. LLM agent with concept-based tools → open-vocabulary fallback
5. Answer guardrails → verify before returning
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
            result = super().answer(question, bundle, reference_date, structured_intent)
            result.answered_by = "structured_intent"
            return result

        resolved = resolve_concept(question)
        if resolved:
            result = self._execute_resolved(resolved, bundle, reference_date)
            if result.value is True or result.insufficient_data:
                result.answered_by = "resolver"
                return result
            if result.value is not False:
                result.answered_by = "resolver"
                return result
            # Negative boolean from resolver → fall through to LLM
            # (the resolver's negative is not definitive without the full pipeline)

        return self._llm_resolve(question, bundle, reference_date)

    def _llm_resolve(
        self, question: str, bundle: dict, reference_date: date,
    ) -> QAAnswer:
        """Try LLM query plan synthesis, falling back to agent."""
        from acp_writer.tools.answer_guardrails import verify_answer
        from acp_writer.tools.bundle_inventory import build_bundle_inventory

        condensed = serialize_ips(bundle)
        llm = self._get_llm()
        inventory = build_bundle_inventory(bundle)
        inventory_text = inventory.render_for_llm()

        plan = generate_query_plan(question, condensed, reference_date, llm, inventory_text=inventory_text)
        if plan:
            result = super().answer(
                question, bundle, reference_date,
                structured_intent=plan,
            )
            if not result.insufficient_data:
                result.answered_by = "query_plan"
                return result

        from acp_writer.tools.qa_agent import agent_answer

        agent_result = agent_answer(question, bundle, reference_date, llm)

        verified = verify_answer(agent_result, question, bundle, inventory)

        if verified.get("guardrail"):
            return QAAnswer(
                value=None,
                kind="insufficient_data",
                provenance=verified.get("provenance", []),
                insufficient_data=True,
                error=f"guardrail:{verified['guardrail']}",
                answered_by="guardrail_downgrade",
            )

        return QAAnswer(
            value=verified.get("answer"),
            kind=self._infer_kind(verified.get("answer")),
            provenance=verified.get("provenance", []),
            insufficient_data=verified.get("insufficient_data", False),
            error=verified.get("error"),
            answered_by="agent",
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
