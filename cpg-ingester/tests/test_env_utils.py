"""Tests for the shared env-var parsing helpers."""

import pytest

from cpg_ingester.env_utils import env_flag, env_int


class TestEnvFlag:
    def test_unset_returns_default(self, monkeypatch):
        monkeypatch.delenv("MY_FLAG", raising=False)
        assert env_flag("MY_FLAG", default=True) is True
        assert env_flag("MY_FLAG", default=False) is False

    @pytest.mark.parametrize("val", ["", "   ", "\t"])
    def test_empty_or_whitespace_returns_default(self, monkeypatch, val):
        monkeypatch.setenv("MY_FLAG", val)
        assert env_flag("MY_FLAG", default=True) is True
        assert env_flag("MY_FLAG", default=False) is False

    @pytest.mark.parametrize("val", ["0", "false", "FALSE", "no", "off", " Off "])
    def test_falsey_values(self, monkeypatch, val):
        monkeypatch.setenv("MY_FLAG", val)
        assert env_flag("MY_FLAG", default=True) is False

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on", "anything"])
    def test_truthy_values(self, monkeypatch, val):
        monkeypatch.setenv("MY_FLAG", val)
        assert env_flag("MY_FLAG", default=False) is True


class TestEnvInt:
    def test_unset_returns_default(self, monkeypatch):
        monkeypatch.delenv("MY_INT", raising=False)
        assert env_int("MY_INT", 100) == 100

    @pytest.mark.parametrize("val", ["", "   "])
    def test_empty_returns_default(self, monkeypatch, val):
        monkeypatch.setenv("MY_INT", val)
        assert env_int("MY_INT", 100) == 100

    def test_valid_int(self, monkeypatch):
        monkeypatch.setenv("MY_INT", "42")
        assert env_int("MY_INT", 100) == 42

    def test_whitespace_padded_int(self, monkeypatch):
        monkeypatch.setenv("MY_INT", "  7 ")
        assert env_int("MY_INT", 100) == 7

    def test_unparseable_returns_default_and_warns(self, monkeypatch, caplog):
        monkeypatch.setenv("MY_INT", "not-a-number")
        assert env_int("MY_INT", 100) == 100
        assert any("not an integer" in r.message for r in caplog.records)
