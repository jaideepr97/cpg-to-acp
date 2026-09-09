"""Monolith ⇄ split-path parity guard.

The systemic bug behind issue #169's conflict miss: the cluster deployment
splits the LangGraph pipeline across per-pod FastAPI services that hand-
re-implement the node ordering. A node added to the monolith graph
(``pipeline.build_pipeline``) can therefore silently never run in the split
deployment — exactly what happened to ``conflict_analyst``.

This is a cheap structural guard, not a behavioral equivalence proof: it asserts
that every node the monolith runs is at least *referenced* by some split service
module. It will fail loudly the next time a node is wired into the monolith but
forgotten in the split path. The architectural fix (one shared phase module both
paths call) is tracked in issue #174; until then, this test is the backstop.
"""

from pathlib import Path

from acp_writer.pipeline import build_pipeline

_SERVICES_DIR = Path(__file__).resolve().parent.parent / "src" / "acp_writer" / "services"


def _monolith_nodes() -> set[str]:
    graph = build_pipeline()
    return {n for n in graph.nodes if not n.startswith("__")}


def _split_service_source() -> str:
    return "\n".join(p.read_text() for p in _SERVICES_DIR.glob("*.py"))


def test_every_monolith_node_is_wired_into_a_split_service():
    nodes = _monolith_nodes()
    assert nodes, "expected the monolith pipeline to declare nodes"

    source = _split_service_source()
    missing = sorted(n for n in nodes if n not in source)

    assert not missing, (
        "These monolith pipeline nodes are not referenced by any split service "
        f"and would silently never run in the cluster deployment: {missing}. "
        "Wire them into the appropriate acp_writer/services/*.py handler "
        "(see the phase-runner fast-follow issue #174)."
    )


def test_conflict_analyst_specifically_runs_in_split_compose():
    # Regression pin for #169: conflict_analyst must run in the split compose
    # service (llm_reasoning), not only in the monolith graph.
    llm_reasoning_src = (_SERVICES_DIR / "llm_reasoning.py").read_text()
    assert "conflict_analyst" in llm_reasoning_src
