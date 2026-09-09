"""C1: the shared LLM-JSON parsing helper (issue #169 review)."""

import json

import pytest

from acp_writer.llm_json import loads_json, strip_code_fence


class TestStripCodeFence:
    def test_bare_text_unchanged(self):
        assert strip_code_fence('{"a": 1}') == '{"a": 1}'

    def test_surrounding_whitespace_trimmed(self):
        assert strip_code_fence('\n  {"a": 1}  \n') == '{"a": 1}'

    def test_json_language_tag_fence(self):
        assert strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_plain_fence(self):
        assert strip_code_fence('```\n{"a": 1}\n```') == '{"a": 1}'

    def test_missing_closing_fence_keeps_last_content_line(self):
        # Regression: the old plan_composer copy always dropped the last line,
        # even when it was content rather than a closing fence.
        assert strip_code_fence('```json\n{"a": 1}') == '{"a": 1}'

    def test_multiline_body_preserved(self):
        assert strip_code_fence('```json\n{\n  "a": 1\n}\n```') == '{\n  "a": 1\n}'


class TestLoadsJson:
    def test_parses_fenced(self):
        assert loads_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_parses_bare(self):
        assert loads_json('{"a": [1, 2]}') == {"a": [1, 2]}

    def test_raises_on_malformed(self):
        with pytest.raises(json.JSONDecodeError):
            loads_json("not json at all")
