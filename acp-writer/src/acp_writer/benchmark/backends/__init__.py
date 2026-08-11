"""Backend registry for the benchmark harness."""

from typing import Callable

from acp_writer.benchmark.protocol import QABackend


def _make_current() -> QABackend:
    from acp_writer.benchmark.backends.current import CurrentImplementationBackend

    return CurrentImplementationBackend()


def _make_llm_assisted() -> QABackend:
    from acp_writer.benchmark.backends.llm_assisted import LLMAssistedBackend

    return LLMAssistedBackend()


def _make_graph() -> QABackend:
    from acp_writer.benchmark.backends.graph_backed import GraphBackedBackend

    return GraphBackedBackend()


BACKENDS: dict[str, Callable[[], QABackend]] = {
    "current": _make_current,
    "llm-assisted": _make_llm_assisted,
    "graph": _make_graph,
}
