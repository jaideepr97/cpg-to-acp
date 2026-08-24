"""Small env-var parsing helpers, shared across cpg-ingester nodes.

Component-local on purpose — these live here, not in ``shared/`` (AGENTS.md says
use ``shared/`` sparingly, and these are only needed inside cpg-ingester). They
exist so the OCR gate (``docling_agent._ocr_enabled``) and the figure-interpreter
gate (``figure_interpreter._interpretation_enabled``) parse env the same way
instead of drifting apart as two hand-rolled copies.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_FALSEY = {"0", "false", "no", "off"}


def env_flag(name: str, default: bool = True) -> bool:
    """Parse a boolean env var.

    Unset, empty, or whitespace-only → ``default``. (``VAR: ""`` is the standard
    way to blank a variable in a Helm/compose override, so it must mean "use the
    default", not "on".) Otherwise the value is falsey iff it is one of
    ``0``/``false``/``no``/``off`` (case-insensitive, stripped); any other
    non-empty value is truthy.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in _FALSEY


def env_int(name: str, default: int) -> int:
    """Parse an integer env var; unset/empty/unparseable → ``default``.

    Logs a warning on an unparseable value so a typo in a deploy config is
    visible rather than silently falling back.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(
            "Env var %s=%r is not an integer; using default %d", name, raw, default
        )
        return default
