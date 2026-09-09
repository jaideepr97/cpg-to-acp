"""F13: meaningful conflict-path functions must carry @mlflow.trace.

AGENTS.md requires every function doing meaningful work (data transformations,
external calls) to be traced. These conflict read-back / provenance / normalize
functions were previously untraced. ``mlflow.trace`` marks the wrapped callable
with ``__mlflow_traced__`` — assert it is present.
"""

from acp_writer.planning_brief import coerce_conflicts
from acp_writer.services.ai_transparency import (
    build_conflict_provenance,
    plan_conflict_from_provenance,
)
from acp_writer.services.artifact_resolver import (
    plan_activity_from_entry,
    plan_conflict_from_entry,
    plan_goal_from_entry,
)


def test_conflict_functions_are_traced():
    for fn in (
        coerce_conflicts,
        build_conflict_provenance,
        plan_conflict_from_provenance,
        plan_conflict_from_entry,
        plan_goal_from_entry,
        plan_activity_from_entry,
    ):
        assert getattr(fn, "__mlflow_traced__", False), f"{fn.__name__} is not @mlflow.trace-decorated"
