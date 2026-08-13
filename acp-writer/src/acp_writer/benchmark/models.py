"""Data models for the clinical QA benchmark harness."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from acp_writer.tools.qa_result import QAAnswer  # noqa: F401 — re-exported


@dataclass
class BenchmarkCase:
    """A single benchmark test case loaded from a suite JSON file."""

    id: str
    question: str
    bundle: str
    reference_date: date
    expected: dict[str, Any]
    category: str
    level: int
    structured_intent: dict[str, Any] | None = None
    expected_provenance: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BenchmarkCase":
        return cls(
            id=d["id"],
            question=d["question"],
            bundle=d["bundle"],
            reference_date=date.fromisoformat(d["reference_date"]),
            expected=d["expected"],
            category=d["category"],
            level=d["level"],
            structured_intent=d.get("structured_intent"),
            expected_provenance=d.get("expected_provenance", []),
        )


@dataclass
class CaseScore:
    """Scoring result for one test case."""

    test_id: str
    correct: bool
    provenance_correct: bool
    hallucination: bool
    error: str | None = None
    expected: Any = None
    actual: Any = None


@dataclass
class CategoryResult:
    """Results for a single category or level slice."""

    total: int = 0
    correct: int = 0
    provenance_correct: int = 0
    hallucinations: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total > 0 else 0.0


@dataclass
class SuiteResult:
    """Aggregated results for an entire suite run."""

    suite_name: str
    backend_name: str
    total: int
    correct: int
    provenance_correct: int
    hallucinations: int
    errors: int
    by_category: dict[str, CategoryResult] = field(default_factory=dict)
    by_level: dict[int, CategoryResult] = field(default_factory=dict)
    case_scores: list[CaseScore] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total > 0 else 0.0

    @property
    def provenance_accuracy(self) -> float:
        scored = sum(1 for cs in self.case_scores if not cs.error)
        prov_correct = sum(
            1 for cs in self.case_scores if cs.provenance_correct and not cs.error
        )
        return prov_correct / scored if scored > 0 else 0.0
