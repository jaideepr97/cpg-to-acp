"""Tests for benchmark scoring logic."""

from datetime import date

from acp_writer.benchmark.models import QAAnswer, BenchmarkCase
from acp_writer.benchmark.scoring import score_case


def _tc(expected_kind, expected_value=None, provenance=None):
    exp = {"kind": expected_kind}
    if expected_value is not None:
        exp["value"] = expected_value
    return BenchmarkCase(
        id="test-001",
        question="test",
        bundle="bundles/test.json",
        reference_date=date(2026, 6, 1),
        expected=exp,
        category="test",
        level=1,
        expected_provenance=provenance or [],
    )


class TestNumberScoring:
    def test_exact_match(self):
        cs = score_case(_tc("number", 142), QAAnswer(value=142, kind="number"))
        assert cs.correct

    def test_mismatch(self):
        cs = score_case(_tc("number", 142), QAAnswer(value=140, kind="number"))
        assert not cs.correct

    def test_tolerance(self):
        cs = score_case(_tc("number", 142), QAAnswer(value=140, kind="number"), numeric_tolerance=2.5)
        assert cs.correct

    def test_tolerance_boundary(self):
        cs = score_case(_tc("number", 142), QAAnswer(value=139, kind="number"), numeric_tolerance=2.5)
        assert not cs.correct

    def test_none_value(self):
        cs = score_case(_tc("number", 142), QAAnswer(value=None, kind="number"))
        assert not cs.correct


class TestBooleanScoring:
    def test_true_match(self):
        cs = score_case(_tc("boolean", True), QAAnswer(value=True, kind="boolean"))
        assert cs.correct

    def test_false_match(self):
        cs = score_case(_tc("boolean", False), QAAnswer(value=False, kind="boolean"))
        assert cs.correct

    def test_mismatch(self):
        cs = score_case(_tc("boolean", True), QAAnswer(value=False, kind="boolean"))
        assert not cs.correct


class TestCountScoring:
    def test_exact_match(self):
        cs = score_case(_tc("count", 5), QAAnswer(value=5, kind="count"))
        assert cs.correct

    def test_mismatch(self):
        cs = score_case(_tc("count", 5), QAAnswer(value=4, kind="count"))
        assert not cs.correct


class TestCodeScoring:
    def test_exact_match(self):
        cs = score_case(_tc("code", "active"), QAAnswer(value="active", kind="code"))
        assert cs.correct

    def test_mismatch(self):
        cs = score_case(_tc("code", "active"), QAAnswer(value="inactive", kind="code"))
        assert not cs.correct


class TestInsufficientData:
    def test_correct_insufficient(self):
        cs = score_case(
            _tc("insufficient_data"),
            QAAnswer(value=None, kind="insufficient_data", insufficient_data=True),
        )
        assert cs.correct
        assert not cs.hallucination

    def test_hallucination(self):
        cs = score_case(
            _tc("insufficient_data"),
            QAAnswer(value=142, kind="number", insufficient_data=False),
        )
        assert not cs.correct
        assert cs.hallucination

    def test_error_not_hallucination(self):
        cs = score_case(
            _tc("insufficient_data"),
            QAAnswer(value=None, kind="insufficient_data", insufficient_data=False, error="failed"),
        )
        assert not cs.correct
        assert not cs.hallucination


class TestProvenanceScoring:
    def test_exact_set_match(self):
        cs = score_case(
            _tc("number", 142, provenance=["Observation/bp-1", "Observation/bp-2"]),
            QAAnswer(value=142, kind="number", provenance=["Observation/bp-2", "Observation/bp-1"]),
        )
        assert cs.provenance_correct

    def test_missing_provenance(self):
        cs = score_case(
            _tc("number", 142, provenance=["Observation/bp-1"]),
            QAAnswer(value=142, kind="number", provenance=[]),
        )
        assert not cs.provenance_correct

    def test_empty_expected_provenance(self):
        cs = score_case(
            _tc("number", 142),
            QAAnswer(value=142, kind="number", provenance=[]),
        )
        assert cs.provenance_correct


class TestErrorHandling:
    def test_error_is_incorrect(self):
        cs = score_case(
            _tc("number", 142),
            QAAnswer(value=None, kind="number", error="extraction failed"),
        )
        assert not cs.correct
        assert not cs.hallucination

    def test_insufficient_data_when_value_expected(self):
        cs = score_case(
            _tc("number", 142),
            QAAnswer(value=None, kind="insufficient_data", insufficient_data=True),
        )
        assert not cs.correct
