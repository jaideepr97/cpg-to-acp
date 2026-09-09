"""Tests for the Plan Composer system-prompt assembly (F17a).

The composer runs in two modes. AUTHORING (no prior brief) must preserve every
inter-guideline conflict; REVISION (a request-changes loop with a prior brief)
must instead revise the prior plan minimally and apply the clinician's directed
resolutions. ``compose_system_prompt(revision)`` selects the mode section while
keeping a shared HEAD + EXAMPLES; authoring output stays byte-identical to the
pre-F17 single prompt.
"""

from acp_writer.prompts.plan_composer import (
    PLAN_COMPOSER_AUTHORING,
    PLAN_COMPOSER_EXAMPLES,
    PLAN_COMPOSER_HEAD,
    PLAN_COMPOSER_REVISION,
    PLAN_COMPOSER_SYSTEM,
    compose_system_prompt,
)


def test_authoring_mode_preserves_conflicts_not_revision():
    prompt = compose_system_prompt(revision=False)
    # Shared core is always present.
    assert PLAN_COMPOSER_HEAD in prompt
    assert PLAN_COMPOSER_EXAMPLES in prompt
    # Authoring-only guidance: preserve conflicts, do NOT harmonize.
    assert PLAN_COMPOSER_AUTHORING in prompt
    assert "Preserving conflicts between guidelines" in prompt
    assert "merge, reconcile, average, harmonize" in prompt.replace("\n", " ")
    # The revision section must NOT leak into authoring mode.
    assert PLAN_COMPOSER_REVISION not in prompt
    assert "Revising an existing care plan" not in prompt


def test_revision_mode_revises_minimally_not_authoring():
    prompt = compose_system_prompt(revision=True)
    # Shared core is still present.
    assert PLAN_COMPOSER_HEAD in prompt
    assert PLAN_COMPOSER_EXAMPLES in prompt
    # Revision-only guidance: authoritative base, directed resolutions, no adds.
    assert PLAN_COMPOSER_REVISION in prompt
    assert "Revising an existing care plan" in prompt
    assert "AUTHORITATIVE BASE" in prompt
    assert "NO unrequested additions" in prompt
    # The authoring "preserve every conflict" block must NOT apply here.
    assert PLAN_COMPOSER_AUTHORING not in prompt
    assert "Preserving conflicts between guidelines" not in prompt


def test_authoring_alias_is_byte_identical_to_pre_f17_prompt():
    # Back-compat: the module still exposes PLAN_COMPOSER_SYSTEM as the
    # authoring-mode prompt so anything importing the old constant is unchanged.
    assert PLAN_COMPOSER_SYSTEM == compose_system_prompt(revision=False)


def test_modes_share_head_and_examples_but_differ_in_middle():
    authoring = compose_system_prompt(revision=False)
    revision = compose_system_prompt(revision=True)
    assert authoring != revision
    # Both anchor on the same head + examples.
    for prompt in (authoring, revision):
        assert prompt.startswith(PLAN_COMPOSER_HEAD)
        assert prompt.endswith(PLAN_COMPOSER_EXAMPLES)
