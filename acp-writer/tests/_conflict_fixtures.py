"""Shared conflict-analyst test scaffolding (C3).

Both the node-level (``test_conflict_analyst``) and split-path
(``test_split_compose_conflicts``) suites drive the analyst with the same
canonical overlap conflict and the same mocked LLM. Kept here once so the two
don't drift. Underscore-prefixed so pytest does not collect it as a test module.
"""

import json
from unittest.mock import MagicMock

# Canonical "two guidelines both recommend a diet" overlap. Superset shape:
# carries rationale AND suggested_resolution so node-level tests that assert the
# resolution round-trips still pass; split-path tests only check it surfaces.
OVERLAP_JSON = json.dumps({
    "conflicts": [{
        "category": "overlap",
        "severity": "info",
        "description": "Both guidelines recommend a healthy diet",
        "rationale": "Two lifestyle diet activities are substantially the same",
        "suggested_resolution": "Combine the two diet activities into a single lifestyle activity",
        "confidence": "high",
        "goal_indices": [],
        "activity_indices": [0, 1],
        "sources": [
            {"cpg_id": "SYN-HTN-2026-001", "recommendation_id": "htn-rec-004", "excerpt": "healthy diet"},
            {"cpg_id": "SYN-DM2-2026-001", "recommendation_id": "dm2-rec-004", "excerpt": "heart-healthy diet"},
        ],
    }]
})


def mock_llm(*contents: str) -> MagicMock:
    """A mock LLM whose ``invoke`` yields the given response contents.

    One content → returned repeatably (``return_value``); several → yielded in
    order across successive calls (``side_effect``), which drives retry tests.
    """
    mock = MagicMock()
    if len(contents) == 1:
        resp = MagicMock()
        resp.content = contents[0]
        mock.invoke.return_value = resp
        return mock
    responses = []
    for c in contents:
        r = MagicMock()
        r.content = c
        responses.append(r)
    mock.invoke.side_effect = responses
    return mock
