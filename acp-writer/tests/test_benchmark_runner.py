"""Tests for benchmark runner — suite loading, execution, aggregation."""

import json
import tempfile
from datetime import date
from pathlib import Path

import pytest

from acp_writer.benchmark.models import QAAnswer, BenchmarkCase
from acp_writer.benchmark.runner import load_suite, _aggregate


class TestSuiteLoading:
    def test_load_smoke_suite(self):
        cases = load_suite("smoke")
        assert len(cases) == 50
        assert all(isinstance(tc, BenchmarkCase) for tc in cases)

    def test_load_nonexistent_suite(self):
        with pytest.raises(FileNotFoundError):
            load_suite("nonexistent")

    def test_parsed_fields(self):
        cases = load_suite("smoke")
        first = cases[0]
        assert first.id == "smoke-lookup-001"
        assert isinstance(first.reference_date, date)
        assert first.category == "lookup"
        assert first.level in (1, 2, 3, 4)


class TestAggregation:
    def test_basic_aggregation(self):
        from acp_writer.benchmark.models import CaseScore

        cases = [
            BenchmarkCase(id="t1", question="q", bundle="b", reference_date=date(2026, 6, 1),
                     expected={"kind": "number", "value": 1}, category="lookup", level=1),
            BenchmarkCase(id="t2", question="q", bundle="b", reference_date=date(2026, 6, 1),
                     expected={"kind": "boolean", "value": True}, category="boolean", level=1),
        ]
        scores = [
            CaseScore(test_id="t1", correct=True, provenance_correct=True, hallucination=False),
            CaseScore(test_id="t2", correct=False, provenance_correct=False, hallucination=False),
        ]

        result = _aggregate("test", "current", cases, scores)
        assert result.total == 2
        assert result.correct == 1
        assert result.accuracy == 0.5
        assert "lookup" in result.by_category
        assert result.by_category["lookup"].correct == 1
        assert result.by_category["boolean"].correct == 0
