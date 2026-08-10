"""Backend registry for the benchmark harness."""

from typing import Callable

from acp_writer.benchmark.protocol import QABackend


def _make_current() -> QABackend:
    from acp_writer.benchmark.backends.current import CurrentImplementationBackend

    return CurrentImplementationBackend()


BACKENDS: dict[str, Callable[[], QABackend]] = {
    "current": _make_current,
}
