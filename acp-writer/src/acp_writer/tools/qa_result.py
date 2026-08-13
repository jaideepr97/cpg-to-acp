"""QA result types shared between production and benchmark code."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QAAnswer:
    """Answer from a QA resolution — used by guardrails (production)
    and benchmark backends.
    """
    value: Any
    kind: str
    provenance: list[str] = field(default_factory=list)
    insufficient_data: bool = False
    error: str | None = None
    answered_by: str | None = None
    resolution_basis: str | None = None
