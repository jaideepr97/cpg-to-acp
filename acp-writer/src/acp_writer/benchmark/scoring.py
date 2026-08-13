"""Scoring logic for clinical QA benchmark (v2).

Pure functions — no side effects, no I/O. Takes a BenchmarkCase and QAAnswer,
returns a CaseScore.

v2 (2026-08-13): boolean comparisons require actual boolean type — numeric
values no longer coerce to True/False via Python truthiness.
"""

from typing import Any

from acp_writer.benchmark.models import CaseScore, QAAnswer, BenchmarkCase


def score_case(
    test_case: BenchmarkCase,
    answer: QAAnswer,
    numeric_tolerance: float = 0.0,
) -> CaseScore:
    """Score a single test case answer against its expected value."""
    expected_kind = test_case.expected["kind"]
    expected_value = test_case.expected.get("value")

    if expected_kind == "insufficient_data":
        hallucination = (
            not answer.insufficient_data
            and answer.value is not None
        )
        return CaseScore(
            test_id=test_case.id,
            correct=answer.insufficient_data,
            provenance_correct=_score_provenance(test_case, answer),
            hallucination=hallucination,
            expected="insufficient_data",
            actual=answer.value if not answer.insufficient_data else "insufficient_data",
        )

    if answer.error is not None:
        return CaseScore(
            test_id=test_case.id,
            correct=False,
            provenance_correct=_score_provenance(test_case, answer),
            hallucination=False,
            error=answer.error,
            expected=expected_value,
            actual=answer.value,
        )

    if answer.insufficient_data:
        return CaseScore(
            test_id=test_case.id,
            correct=False,
            provenance_correct=_score_provenance(test_case, answer),
            hallucination=False,
            expected=expected_value,
            actual="insufficient_data",
        )

    correct = _compare_values(expected_kind, expected_value, answer.value, numeric_tolerance)

    return CaseScore(
        test_id=test_case.id,
        correct=correct,
        provenance_correct=_score_provenance(test_case, answer),
        hallucination=False,
        expected=expected_value,
        actual=answer.value,
    )


def _compare_values(
    kind: str,
    expected: Any,
    actual: Any,
    tolerance: float,
) -> bool:
    if actual is None:
        return False

    if kind == "boolean":
        if not isinstance(actual, bool):
            return False
        return actual == bool(expected)

    if kind == "code":
        return str(actual) == str(expected)

    if kind == "count":
        try:
            return int(actual) == int(expected)
        except (ValueError, TypeError):
            return False

    if kind == "number":
        try:
            return abs(float(actual) - float(expected)) <= tolerance
        except (ValueError, TypeError):
            return False

    return False


def _score_provenance(test_case: BenchmarkCase, answer: QAAnswer) -> bool:
    if not test_case.expected_provenance:
        return True
    return set(test_case.expected_provenance) == set(answer.provenance)
