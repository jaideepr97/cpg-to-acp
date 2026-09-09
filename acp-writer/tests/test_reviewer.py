"""Tests for the reviewer-identity seam (WS5).

ReviewerContext is the single thing every downstream consumer (approve path,
verifier Humanagent, conflict acknowledgment) reads — its source (config /
request / smart) is deliberately opaque to them.
"""

import pytest

from acp_writer.services.reviewer import (
    ReviewerContext,
    default_reviewer,
    reviewer_from_payload,
)

_ENV_KEYS = (
    "ACP_REVIEWER_DISPLAY",
    "ACP_REVIEWER_REFERENCE",
    "ACP_REVIEWER_ID_SYSTEM",
    "ACP_REVIEWER_ID_VALUE",
)


@pytest.fixture(autouse=True)
def _clear_reviewer_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    yield


class TestAsAgentWho:
    def test_display_only(self):
        who = ReviewerContext(display="Dr. Smith").as_agent_who()
        assert who == {"display": "Dr. Smith"}

    def test_reference_included(self):
        who = ReviewerContext(
            display="Dr. Smith", reference="Practitioner/p1"
        ).as_agent_who()
        assert who["reference"] == "Practitioner/p1"

    def test_identifier_included(self):
        who = ReviewerContext(
            display="Dr. Smith",
            identifier_system="http://hl7.org/fhir/sid/us-npi",
            identifier_value="1234567890",
        ).as_agent_who()
        assert who["identifier"] == {
            "system": "http://hl7.org/fhir/sid/us-npi",
            "value": "1234567890",
        }

    def test_identifier_value_only(self):
        who = ReviewerContext(display="X", identifier_value="42").as_agent_who()
        assert who["identifier"] == {"value": "42"}


class TestDefaultReviewer:
    def test_defaults_when_no_env(self):
        r = default_reviewer()
        assert r.display == "Demo Clinician"
        assert r.reference == "Practitioner/demo-clinician"
        assert r.source == "config"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("ACP_REVIEWER_DISPLAY", "Dr. Alice")
        monkeypatch.setenv("ACP_REVIEWER_REFERENCE", "Practitioner/alice")
        monkeypatch.setenv("ACP_REVIEWER_ID_SYSTEM", "http://hl7.org/fhir/sid/us-npi")
        monkeypatch.setenv("ACP_REVIEWER_ID_VALUE", "999")
        r = default_reviewer()
        assert r.display == "Dr. Alice"
        assert r.reference == "Practitioner/alice"
        assert r.identifier_system == "http://hl7.org/fhir/sid/us-npi"
        assert r.identifier_value == "999"

    def test_blank_reference_becomes_none(self, monkeypatch):
        monkeypatch.setenv("ACP_REVIEWER_REFERENCE", "")
        assert default_reviewer().reference is None


class TestReviewerFromPayload:
    def test_none_yields_default(self):
        r = reviewer_from_payload(None)
        assert r.display == "Demo Clinician"
        assert r.source == "config"

    def test_empty_yields_default(self):
        assert reviewer_from_payload({}).display == "Demo Clinician"

    def test_request_override(self):
        r = reviewer_from_payload({
            "display": "Dr. Bob",
            "reference": "Practitioner/bob",
            "identifierSystem": "sys",
            "identifierValue": "7",
        })
        assert r.display == "Dr. Bob"
        assert r.reference == "Practitioner/bob"
        assert r.identifier_system == "sys"
        assert r.identifier_value == "7"
        assert r.source == "request"

    def test_partial_override_falls_back_to_default_reference(self):
        # display given, reference omitted -> keep the config default reference.
        r = reviewer_from_payload({"display": "Dr. Bob"})
        assert r.display == "Dr. Bob"
        assert r.reference == "Practitioner/demo-clinician"

    def test_legacy_clinician_shortcut(self):
        # Callers translate a bare clinician string into {"display": ...}.
        r = reviewer_from_payload({"display": "Dr. Legacy"})
        assert r.display == "Dr. Legacy"

    def test_clinician_kwarg_used_when_no_payload(self):
        # F12: the legacy bare-clinician reconciliation lives here now (one shim),
        # not copy-pasted into each endpoint.
        r = reviewer_from_payload(None, clinician="Dr. Legacy")
        assert r.display == "Dr. Legacy"
        assert r.source == "request"

    def test_payload_wins_over_clinician_kwarg(self):
        # A structured reviewer payload takes precedence over the legacy string.
        r = reviewer_from_payload({"display": "Dr. Structured"}, clinician="Dr. Legacy")
        assert r.display == "Dr. Structured"

    def test_no_payload_no_clinician_yields_default(self):
        assert reviewer_from_payload(None, clinician=None).display == "Demo Clinician"
        assert reviewer_from_payload(None, clinician="").display == "Demo Clinician"
