"""Tests for CurrentImplementationBackend."""

import json
from datetime import date
from pathlib import Path

from acp_writer.benchmark.backends.current import CurrentImplementationBackend

PROJECT_ROOT = Path(__file__).parent.parent.parent
BUNDLES_DIR = PROJECT_ROOT / "acp-writer" / "benchmarks" / "bundles"


def _load(name: str) -> dict:
    return json.loads((BUNDLES_DIR / name).read_text())


class TestObservationLookup:
    def test_systolic_bp_via_structured_intent(self):
        backend = CurrentImplementationBackend()
        bundle = _load("htn-temporal-01.json")
        answer = backend.answer(
            question="systolic bp",
            bundle=bundle,
            reference_date=date(2026, 6, 1),
            structured_intent={"function": "latest_value", "params": {"code": "http://loinc.org|8480-6"}},
        )
        assert answer.value == 144
        assert answer.kind == "number"
        assert not answer.insufficient_data

    def test_diastolic_bp_via_structured_intent(self):
        backend = CurrentImplementationBackend()
        bundle = _load("htn-temporal-01.json")
        answer = backend.answer(
            question="diastolic bp",
            bundle=bundle,
            reference_date=date(2026, 6, 1),
            structured_intent={"function": "latest_value", "params": {"code": "http://loinc.org|8462-4"}},
        )
        assert answer.value == 91
        assert answer.kind == "number"


class TestConditionCheck:
    def test_active_condition_present(self):
        backend = CurrentImplementationBackend()
        bundle = _load("htn-temporal-01.json")
        answer = backend.answer(
            question="has hypertension",
            bundle=bundle,
            reference_date=date(2026, 6, 1),
            structured_intent={"function": "has_condition", "params": {"code": "http://snomed.info/sct|59621000"}},
        )
        assert answer.value is True
        assert answer.kind == "boolean"

    def test_absent_condition(self):
        backend = CurrentImplementationBackend()
        bundle = _load("htn-temporal-01.json")
        answer = backend.answer(
            question="has diabetes",
            bundle=bundle,
            reference_date=date(2026, 6, 1),
            structured_intent={"function": "has_condition", "params": {"code": "http://snomed.info/sct|44054006"}},
        )
        assert answer.value is False
        assert answer.kind == "boolean"


class TestTemporalFunction:
    def test_observation_count_works(self):
        backend = CurrentImplementationBackend()
        bundle = _load("htn-temporal-01.json")
        answer = backend.answer(
            question="count of high BP readings",
            bundle=bundle,
            reference_date=date(2026, 6, 1),
            structured_intent={"function": "observation_count", "params": {"code": "http://loinc.org|8480-6", "duration": "P3M", "threshold": 140, "comparator": "ge"}},
        )
        assert not answer.insufficient_data
        assert answer.value == 5
        assert answer.kind == "count"

    def test_unsupported_function_returns_insufficient_data(self):
        backend = CurrentImplementationBackend()
        bundle = _load("htn-temporal-01.json")
        answer = backend.answer(
            question="unknown query",
            bundle=bundle,
            reference_date=date(2026, 6, 1),
            structured_intent={"function": "totally_unknown_function", "params": {"code": "http://loinc.org|8480-6"}},
        )
        assert answer.insufficient_data


class TestVariableMapFallback:
    def test_systolic_bp_from_question_text(self):
        backend = CurrentImplementationBackend()
        bundle = _load("htn-temporal-01.json")
        answer = backend.answer(
            question="What is the systolic bp?",
            bundle=bundle,
            reference_date=date(2026, 6, 1),
        )
        assert answer.value == 144
        assert answer.kind == "number"

    def test_unknown_variable_returns_insufficient(self):
        backend = CurrentImplementationBackend()
        bundle = _load("htn-temporal-01.json")
        answer = backend.answer(
            question="What is the patient's TSH?",
            bundle=bundle,
            reference_date=date(2026, 6, 1),
        )
        assert answer.insufficient_data
