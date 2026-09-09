"""Shared helpers for parsing JSON out of LLM responses.

LLMs routinely wrap JSON in a markdown code fence (```json … ```). Every node
that asks an LLM for JSON needs to strip that fence before ``json.loads``. This
module holds the single implementation so the nodes don't each carry their own
copy (issue #169 review C1).
"""

import json
from typing import Any


def strip_code_fence(text: str) -> str:
    """Strip a surrounding markdown code fence from an LLM response.

    Drops the opening fence line (with any language tag, e.g. ```` ```json ````)
    and the closing fence line when present. Leaves un-fenced text untouched
    apart from trimming surrounding whitespace. Only the last line is dropped
    when it is actually a fence, so a response missing its closing fence keeps
    all of its content.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return text.strip()


def loads_json(content: str) -> Any:
    """Parse JSON from an LLM response, tolerating a markdown code fence.

    Raises ``json.JSONDecodeError`` on malformed JSON — callers that retry or
    degrade gracefully catch it themselves.
    """
    return json.loads(strip_code_fence(content))
