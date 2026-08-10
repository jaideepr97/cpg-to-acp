"""CurrentImplementationBackend — wraps the existing ips_extractor + KNOWN_VARIABLE_MAP.

Faithfully represents what the current acp-writer can answer.
Does not add capabilities beyond what _extract_input_value does today.
"""

import re
from datetime import date
from typing import Any

from acp_writer.benchmark.models import QAAnswer
from acp_writer.nodes.dmn_executor import KNOWN_VARIABLE_MAP
from acp_writer.tools.ips_extractor import (
    extract_allergy,
    extract_condition,
    extract_medication,
    extract_observation,
)

_OBSERVATION_FUNCTIONS = {"latest_value", "observation_value"}
_CONDITION_FUNCTIONS = {"has_condition", "condition_check"}
_MEDICATION_FUNCTIONS = {"has_medication", "medication_check"}
_ALLERGY_FUNCTIONS = {"has_allergy", "allergy_check"}


class CurrentImplementationBackend:
    name: str = "current"

    def answer(
        self,
        question: str,
        bundle: dict[str, Any],
        reference_date: date,
        structured_intent: dict[str, Any] | None = None,
    ) -> QAAnswer:
        if structured_intent is None:
            return self._try_variable_map(question, bundle)

        func = structured_intent.get("function", "")
        params = structured_intent.get("params", {})
        code_str = params.get("code", "")

        if "|" not in code_str:
            return QAAnswer(
                value=None,
                kind="insufficient_data",
                insufficient_data=True,
                error="Cannot parse code from structured_intent",
            )

        system, code = code_str.rsplit("|", 1)

        if func in _OBSERVATION_FUNCTIONS:
            return self._extract_observation(bundle, system, code)

        if func in _CONDITION_FUNCTIONS:
            return self._extract_condition(bundle, system, code)

        if func in _MEDICATION_FUNCTIONS:
            return self._extract_medication(bundle, system, code)

        if func in _ALLERGY_FUNCTIONS:
            return self._extract_allergy(bundle, system, code)

        return QAAnswer(
            value=None,
            kind="insufficient_data",
            insufficient_data=True,
            error=f"Current implementation does not support function: {func}",
        )

    def _extract_observation(
        self, bundle: dict, system: str, code: str
    ) -> QAAnswer:
        result = extract_observation(bundle, system, code)
        if result.found:
            return QAAnswer(
                value=result.value,
                kind="number",
                provenance=[result.fhir_reference] if result.fhir_reference else [],
            )
        return QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)

    def _extract_condition(
        self, bundle: dict, system: str, code: str
    ) -> QAAnswer:
        result = extract_condition(bundle, system, code)
        return QAAnswer(
            value=result.found,
            kind="boolean",
            provenance=[result.fhir_reference] if result.fhir_reference else [],
        )

    def _extract_medication(
        self, bundle: dict, system: str, code: str
    ) -> QAAnswer:
        result = extract_medication(bundle, system, code)
        return QAAnswer(
            value=result.found,
            kind="boolean",
            provenance=[result.fhir_reference] if result.fhir_reference else [],
        )

    def _extract_allergy(
        self, bundle: dict, system: str, code: str
    ) -> QAAnswer:
        result = extract_allergy(bundle, system, code)
        return QAAnswer(
            value=result.found,
            kind="boolean",
            provenance=[result.fhir_reference] if result.fhir_reference else [],
        )

    def _try_variable_map(self, question: str, bundle: dict) -> QAAnswer:
        """Attempt to answer by matching question text to KNOWN_VARIABLE_MAP."""
        key = re.sub(r"([a-z])([A-Z])", r"\1 \2", question).lower().strip()

        for map_key, (system, code, extract_type) in KNOWN_VARIABLE_MAP.items():
            if map_key in key:
                if extract_type == "observation":
                    return self._extract_observation(bundle, system, code)
                elif extract_type == "condition":
                    return self._extract_condition(bundle, system, code)
                elif extract_type == "medication":
                    return self._extract_medication(bundle, system, code)

        return QAAnswer(
            value=None,
            kind="insufficient_data",
            insufficient_data=True,
            error="No matching variable in KNOWN_VARIABLE_MAP",
        )
