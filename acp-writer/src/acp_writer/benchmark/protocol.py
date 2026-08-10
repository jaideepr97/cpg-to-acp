"""QABackend protocol — the pluggable interface for benchmark contenders."""

from datetime import date
from typing import Any, Protocol, runtime_checkable

from acp_writer.benchmark.models import QAAnswer


@runtime_checkable
class QABackend(Protocol):
    """Interface that all benchmark backends must satisfy."""

    name: str

    def answer(
        self,
        question: str,
        bundle: dict[str, Any],
        reference_date: date,
        structured_intent: dict[str, Any] | None = None,
    ) -> QAAnswer: ...
