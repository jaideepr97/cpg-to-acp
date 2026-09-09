"""Tests for the Conflict Analyst node."""

import json
from unittest.mock import MagicMock, patch

from acp_writer.nodes.conflict_analyst import conflict_analyst
from acp_writer.planning_brief import ConflictEntry

from ._conflict_fixtures import OVERLAP_JSON as _OVERLAP_JSON
from ._conflict_fixtures import mock_llm as _mock_llm


def _brief() -> dict:
    return {
        "patient_reference": "Patient/1",
        "applicable_cpgs": ["SYN-HTN-2026-001", "SYN-DM2-2026-001"],
        "goals": [
            {
                "description": "Lower BP to < 140/90",
                "target_measure_code": {"system": "http://loinc.org", "code": "8480-6", "display": "Systolic BP"},
                "target_value": {"high": 140, "unit": "mmHg"},
                "source_cpg": "SYN-HTN-2026-001",
                "source_recommendation_id": "htn-rec-002",
            },
            {
                "description": "Lower BP to < 130/80",
                "target_measure_code": {"system": "http://loinc.org", "code": "8480-6", "display": "Systolic BP"},
                "target_value": {"high": 130, "unit": "mmHg"},
                "source_cpg": "SYN-DM2-2026-001",
                "source_recommendation_id": "dm2-rec-002",
            },
        ],
        "activities": [
            {"type": "lifestyle", "description": "Adopt a healthy diet", "source_cpg": "SYN-HTN-2026-001", "source_recommendation_id": "htn-rec-004"},
            {"type": "lifestyle", "description": "Follow a heart-healthy diet", "source_cpg": "SYN-DM2-2026-001", "source_recommendation_id": "dm2-rec-004"},
            {"type": "medication", "description": "Lisinopril 10mg daily", "code": {"system": "rxnorm", "code": "29046", "display": "Lisinopril"}, "source_cpg": "SYN-HTN-2026-001", "source_recommendation_id": "htn-rec-001"},
        ],
        "conflicts": [],
        "review_status": "approved",
    }


def _state(brief: dict | None = None) -> dict:
    return {
        "planning_brief": brief if brief is not None else _brief(),
        "recommendations": [
            {"id": "htn-rec-004", "title": "Diet", "content": "Adopt a healthy diet", "source_cpg": "SYN-HTN-2026-001"},
            {"id": "dm2-rec-004", "title": "Diet", "content": "Follow a heart-healthy diet", "source_cpg": "SYN-DM2-2026-001"},
        ],
        "condition_codes": [{"display": "Hypertension"}, {"display": "Type 2 diabetes"}],
        "medication_codes": [{"display": "Lisinopril"}],
        "llm_model": "default",
    }


class TestConflictAnalyst:
    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_happy_path(self, mock_get_llm):
        mock_get_llm.return_value = _mock_llm(_OVERLAP_JSON)
        result = conflict_analyst(_state())

        conflicts = result["planning_brief"]["conflicts"]
        assert len(conflicts) == 1
        c = ConflictEntry.model_validate(conflicts[0])
        assert c.category.value == "overlap"
        assert c.activity_indices == [0, 1]
        # F16b: _build_entry carries the analyst's suggested_resolution through.
        assert c.suggested_resolution == (
            "Combine the two diet activities into a single lifestyle activity"
        )
        assert c.id.startswith("conf-")
        assert "conflict_prompt" in result

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_captured_prompt_is_user_only(self, mock_get_llm):
        # C8: conflict_prompt captures only the rendered user prompt, matching
        # the composer path — the ~3.5KB system prompt must not be baked in.
        from acp_writer.prompts.conflict_analyst import CONFLICT_ANALYST_SYSTEM

        mock_get_llm.return_value = _mock_llm(_OVERLAP_JSON)
        result = conflict_analyst(_state())
        captured = result["conflict_prompt"]
        assert captured
        assert CONFLICT_ANALYST_SYSTEM not in captured

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_index_clamping(self, mock_get_llm):
        raw = json.loads(_OVERLAP_JSON)
        raw["conflicts"][0]["activity_indices"] = [0, 99]  # 99 is out of range
        mock_get_llm.return_value = _mock_llm(json.dumps(raw))
        result = conflict_analyst(_state())
        assert result["planning_brief"]["conflicts"][0]["activity_indices"] == [0]

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_drops_entry_with_all_invalid_indices(self, mock_get_llm):
        raw = json.loads(_OVERLAP_JSON)
        raw["conflicts"][0]["activity_indices"] = [99]
        raw["conflicts"][0]["goal_indices"] = [88]
        mock_get_llm.return_value = _mock_llm(json.dumps(raw))
        result = conflict_analyst(_state())
        assert result["planning_brief"]["conflicts"] == []

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_retry_then_succeed(self, mock_get_llm):
        mock = _mock_llm("not json at all", _OVERLAP_JSON)
        mock_get_llm.return_value = mock
        result = conflict_analyst(_state())
        assert len(result["planning_brief"]["conflicts"]) == 1
        assert mock.invoke.call_count == 2

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_degradation_keeps_existing_conflicts(self, mock_get_llm):
        mock_get_llm.return_value = _mock_llm("garbage", "still garbage")
        brief = _brief()
        brief["conflicts"] = [{
            "id": "conf-prior", "category": "overlap", "severity": "info",
            "description": "pre-existing",
            "activity_indices": [0], "sources": [],
        }]
        result = conflict_analyst(_state(brief))
        # Existing conflicts are preserved, run does not raise.
        assert result["planning_brief"]["conflicts"][0]["id"] == "conf-prior"

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_transport_failure_degrades(self, mock_get_llm):
        mock = MagicMock()
        mock.invoke.side_effect = RuntimeError("connection reset")
        mock_get_llm.return_value = mock
        result = conflict_analyst(_state())  # must not raise
        assert result["planning_brief"]["conflicts"] == []

    # NOTE: The composer-conflict merge and status carry-forward tests were
    # removed with F11 (issue #169). The composer no longer detects conflicts,
    # and the analyst is authoritative on each fresh run — there is no
    # carry-forward. Per-conflict status carry-over is deferred to #172, where
    # it will be rebuilt against the conflict Provenances, not brief state.

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_empty_brief_passthrough(self, mock_get_llm):
        brief = _brief()
        brief["goals"] = []
        brief["activities"] = []
        result = conflict_analyst(_state(brief))
        assert result["planning_brief"]["conflicts"] == []
        mock_get_llm.assert_not_called()

    # --- F3: malformed conflict shapes must never crash the advisory step ---

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_string_conflict_items_retry_then_succeed(self, mock_get_llm):
        # A list of bare strings is shape junk — it must drive the one retry
        # (previously it slipped through and crashed _build_entry on str.get()).
        bad = json.dumps({"conflicts": ["Both CPGs recommend a diet"]})
        mock = _mock_llm(bad, _OVERLAP_JSON)
        mock_get_llm.return_value = mock
        result = conflict_analyst(_state())
        assert len(result["planning_brief"]["conflicts"]) == 1
        assert mock.invoke.call_count == 2

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_malformed_source_dropped_conflict_kept(self, mock_get_llm):
        raw = json.loads(_OVERLAP_JSON)
        raw["conflicts"][0]["sources"] = ["not-a-dict", {"cpg_id": 123}]
        mock_get_llm.return_value = _mock_llm(json.dumps(raw))
        result = conflict_analyst(_state())  # must not raise
        conflicts = result["planning_brief"]["conflicts"]
        assert len(conflicts) == 1
        # string source dropped, int cpg_id coerced to str
        assert len(conflicts[0]["sources"]) == 1
        assert conflicts[0]["sources"][0]["cpg_id"] == "123"

    # --- F14: transport error must retry with the ORIGINAL prompt ---

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_transport_error_retries_without_empty_assistant_message(self, mock_get_llm):
        captured: list[list[dict]] = []

        def invoke(messages):
            captured.append([dict(m) for m in messages])
            if len(captured) == 1:
                raise RuntimeError("connection reset")
            r = MagicMock()
            r.content = _OVERLAP_JSON
            return r

        mock = MagicMock()
        mock.invoke.side_effect = invoke
        mock_get_llm.return_value = mock

        result = conflict_analyst(_state())
        assert len(result["planning_brief"]["conflicts"]) == 1
        assert mock.invoke.call_count == 2
        # The retry must reuse the original 2-message prompt — no empty-content
        # assistant turn (some providers 400 on empty messages).
        assert len(captured[1]) == 2
        assert all(m["content"] for m in captured[1])

    # --- F6: distinct same-category conflicts must get distinct ids ---

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_same_category_conflicts_get_distinct_ids(self, mock_get_llm):
        # Two overlaps, same category, same single source — only the referenced
        # activity differs. The content-key must keep their ids distinct.
        raw = {"conflicts": [
            {"category": "overlap", "severity": "info", "description": "diet",
             "goal_indices": [], "activity_indices": [0], "sources": [{"cpg_id": "SYN-HTN-2026-001"}]},
            {"category": "overlap", "severity": "info", "description": "med",
             "goal_indices": [], "activity_indices": [2], "sources": [{"cpg_id": "SYN-HTN-2026-001"}]},
        ]}
        mock_get_llm.return_value = _mock_llm(json.dumps(raw))
        result = conflict_analyst(_state())
        ids = [c["id"] for c in result["planning_brief"]["conflicts"]]
        assert len(ids) == 2
        assert len(set(ids)) == 2

    # --- C5: _content_key discriminates on referenced content, no category arg ---

    def test_content_key_discriminates_and_takes_no_category(self):
        # After C5 the redundant bounds-checks and unused `category` param are
        # gone; callers pass pre-clamped indices. Distinct activities must still
        # produce distinct keys, and identical references identical keys.
        from acp_writer.nodes.conflict_analyst import _content_key

        goals = _brief()["goals"]
        activities = _brief()["activities"]
        key_diet = _content_key([], [0], goals, activities)
        key_med = _content_key([], [2], goals, activities)
        assert key_diet and key_med
        assert key_diet != key_med
        assert _content_key([], [0], goals, activities) == key_diet

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_colliding_ids_are_suffixed(self, mock_get_llm):
        # Two truly identical conflicts collide on the semantic id — the
        # uniquify pass must suffix the second so downstream keys don't clobber.
        one = {"category": "overlap", "severity": "info", "description": "dup",
               "goal_indices": [], "activity_indices": [0], "sources": [{"cpg_id": "SYN-HTN-2026-001"}]}
        mock_get_llm.return_value = _mock_llm(json.dumps({"conflicts": [dict(one), dict(one)]}))
        result = conflict_analyst(_state())
        ids = [c["id"] for c in result["planning_brief"]["conflicts"]]
        assert len(ids) == 2
        assert len(set(ids)) == 2
        assert any(i.endswith("-2") for i in ids)


class TestConflictAnalystRevisionContinuity:
    """F17c: on a request-changes revision, the analyst carries prior conflicts
    forward — resolved or still present — with their ORIGINAL ids, so the review
    UI shows the same conflicts progressing instead of a fresh-looking set."""

    _PRIOR_ID = "conf-known01"

    def _prior_conflict(self) -> dict:
        return {
            "id": self._PRIOR_ID,
            "category": "overlap",
            "severity": "info",
            "description": "Both guidelines recommend a healthy diet",
            "suggested_resolution": "Combine the two diet activities into one",
            "goal_indices": [],
            "activity_indices": [0, 1],
            "sources": [
                {"cpg_id": "SYN-HTN-2026-001", "recommendation_id": "htn-rec-004"},
                {"cpg_id": "SYN-DM2-2026-001", "recommendation_id": "dm2-rec-004"},
            ],
        }

    def _revision_state(self) -> dict:
        state = _state()
        state["prior_planning_brief"] = {"conflicts": [self._prior_conflict()]}
        state["careplan_feedback"] = "resolve all identified conflicts as you suggested"
        return state

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_resolved_conflict_keeps_id_and_records_resolution(self, mock_get_llm):
        # The clinician directed resolution and the plan merged the diets — the
        # analyst re-emits the prior conflict resolved, with empty indices, SAME id.
        llm_out = json.dumps({"conflicts": [{
            "id": self._PRIOR_ID,
            "category": "overlap",
            "status": "resolved",
            "resolution": "Resolve as suggested — merged the two diet activities into one",
            "description": "Both guidelines recommend a healthy diet",
            "goal_indices": [],
            "activity_indices": [],
            "sources": [],
        }]})
        mock_get_llm.return_value = _mock_llm(llm_out)

        result = conflict_analyst(self._revision_state())
        conflicts = result["planning_brief"]["conflicts"]
        assert len(conflicts) == 1
        c = ConflictEntry.model_validate(conflicts[0])
        assert c.id == self._PRIOR_ID  # same id, not recomputed
        assert c.status.value == "resolved"
        assert "merged the two diet activities" in c.resolution
        # sources fell back to the prior conflict's (LLM omitted them)
        assert len(c.sources) == 2

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_surviving_conflict_keeps_id(self, mock_get_llm):
        # The clinician did not resolve it — re-emit with the same id, detected.
        llm_out = json.dumps({"conflicts": [{
            "id": self._PRIOR_ID,
            "category": "overlap",
            "status": "detected",
            "description": "Both guidelines recommend a healthy diet",
            "goal_indices": [],
            "activity_indices": [0, 1],
            "sources": [{"cpg_id": "SYN-HTN-2026-001", "recommendation_id": "htn-rec-004"}],
        }]})
        mock_get_llm.return_value = _mock_llm(llm_out)

        result = conflict_analyst(self._revision_state())
        c = ConflictEntry.model_validate(result["planning_brief"]["conflicts"][0])
        assert c.id == self._PRIOR_ID
        assert c.status.value == "detected"

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_revision_prompt_carries_prior_conflicts_and_comment(self, mock_get_llm):
        from acp_writer.prompts.conflict_analyst import CONFLICT_ANALYST_REVISION

        mock = _mock_llm(json.dumps({"conflicts": []}))
        mock_get_llm.return_value = mock
        conflict_analyst(self._revision_state())

        messages = mock.invoke.call_args[0][0]
        system_msg, user_msg = messages[0]["content"], messages[1]["content"]
        # revision addendum present in the system prompt
        assert CONFLICT_ANALYST_REVISION.strip() in system_msg
        # prior conflict id + clinician instruction present in the user prompt
        assert self._PRIOR_ID in user_msg
        assert "resolve all identified conflicts as you suggested" in user_msg

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_new_conflict_alongside_carried_forward(self, mock_get_llm):
        # A carried-forward resolved prior conflict PLUS a brand-new one (no id →
        # computed, detected). Both survive.
        llm_out = json.dumps({"conflicts": [
            {"id": self._PRIOR_ID, "category": "overlap", "status": "resolved",
             "resolution": "merged", "description": "diets merged",
             "goal_indices": [], "activity_indices": [], "sources": []},
            {"category": "divergent_target", "severity": "warning",
             "description": "BP targets differ", "goal_indices": [0, 1],
             "activity_indices": [], "sources": [{"cpg_id": "SYN-DM2-2026-001"}]},
        ]})
        mock_get_llm.return_value = _mock_llm(llm_out)

        result = conflict_analyst(self._revision_state())
        conflicts = result["planning_brief"]["conflicts"]
        assert len(conflicts) == 2
        by_id = {c["id"]: c for c in conflicts}
        assert by_id[self._PRIOR_ID]["status"] == "resolved"
        fresh = [c for c in conflicts if c["id"] != self._PRIOR_ID][0]
        assert fresh["status"] == "detected"
        assert fresh["category"] == "divergent_target"

    @patch("acp_writer.nodes.conflict_analyst.get_llm")
    def test_authoring_prompt_unchanged_without_prior(self, mock_get_llm):
        from acp_writer.prompts.conflict_analyst import (
            CONFLICT_ANALYST_REVISION,
            CONFLICT_ANALYST_SYSTEM,
        )

        mock = _mock_llm(_OVERLAP_JSON)
        mock_get_llm.return_value = mock
        conflict_analyst(_state())  # no prior_planning_brief

        system_msg = mock.invoke.call_args[0][0][0]["content"]
        assert system_msg == CONFLICT_ANALYST_SYSTEM
        assert CONFLICT_ANALYST_REVISION.strip() not in system_msg
