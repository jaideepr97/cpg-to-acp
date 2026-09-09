"""Tests for the AI Transparency IG resource-construction module."""

import base64

from acp_writer.planning_brief import (
    ConflictCategory,
    ConflictEntry,
    ConflictSeverity,
    ConflictSource,
    ConflictStatus,
)
from acp_writer.services import ai_transparency as ait


class TestCanonicals:
    def test_ig_base_not_hyphenated(self):
        # Regression-lock: the fix from uv/ai-transparency → uv/aitransparency.
        assert ait.IG_BASE == "http://hl7.org/fhir/uv/aitransparency"
        assert "ai-transparency" not in ait.AI_DEVICE_PROFILE
        assert "ai-transparency" not in ait.AI_PROVENANCE_PROFILE

    def test_targetpath_is_stock_fhir(self):
        ext = ait.targetPath_ext("CarePlan.activity[0].detail")
        assert ext["url"] == "http://hl7.org/fhir/StructureDefinition/targetPath"
        assert ext["valueString"] == "CarePlan.activity[0].detail"

    def test_aiast_display(self):
        sec = ait.aiast_security()
        assert sec["code"] == "AIAST"
        assert sec["display"] == "Artificial Intelligence asserted"


class TestDevice:
    def test_device_shape(self):
        d = ait.build_ai_device("dev-1", "gpt-x", app_version="9.9.9")
        assert d["meta"]["profile"] == [ait.AI_DEVICE_PROFILE]
        assert d["type"]["coding"][0]["code"] == "Artificial-Intelligence"
        assert d["extension"][0]["url"] == ait.AIKIND_EXT
        assert d["extension"][0]["valueCodeableConcept"]["coding"][0]["code"] == "Large-Language-Models"
        assert {"value": "gpt-x"} in d["version"]
        assert {"value": "9.9.9"} in d["version"]

    def test_device_unknown_model(self):
        d = ait.build_ai_device("dev-1", None)
        assert {"value": "unknown"} in d["version"]


class TestConfidence:
    def test_medium_maps_to_moderate(self):
        ext = ait.ai_confidence_ext("medium")
        assert ext["url"] == ait.AICONFIDENCE_EXT
        coding = ext["valueCodeableConcept"]["coding"][0]
        assert coding["system"] == ait.CERTAINTY_RATING_CS
        assert coding["code"] == "moderate"

    def test_high_and_low(self):
        assert ait.ai_confidence_ext("high")["valueCodeableConcept"]["coding"][0]["code"] == "high"
        assert ait.ai_confidence_ext("low")["valueCodeableConcept"]["coding"][0]["code"] == "low"

    def test_none_and_unmappable(self):
        assert ait.ai_confidence_ext(None) is None
        assert ait.ai_confidence_ext("") is None
        assert ait.ai_confidence_ext("bogus") is None


class TestInputPrompt:
    def test_docref_base64(self):
        d = ait.build_input_prompt_docref("dr-1", "the prompt", "Rendered prompt: x")
        assert d["meta"]["profile"] == [ait.AI_INPUT_PROMPT_PROFILE]
        assert d["status"] == "current"
        assert d["type"]["coding"][0]["code"] == "AIInputPrompt"
        att = d["content"][0]["attachment"]
        assert att["contentType"] == "text/markdown"
        assert base64.b64decode(att["data"]).decode("utf-8") == "the prompt"

    def test_capture_default_enabled(self, monkeypatch):
        monkeypatch.delenv("ACP_CAPTURE_PROMPTS", raising=False)
        assert ait.prompts_capture_enabled() is True

    def test_capture_disabled(self, monkeypatch):
        monkeypatch.setenv("ACP_CAPTURE_PROMPTS", "false")
        assert ait.prompts_capture_enabled() is False


class TestModelCard:
    def test_url_env(self, monkeypatch):
        monkeypatch.delenv("LLM_MODEL_CARD_URL", raising=False)
        assert ait.model_card_url() is None
        monkeypatch.setenv("LLM_MODEL_CARD_URL", "https://example.org/c.html")
        assert ait.model_card_url() == "https://example.org/c.html"

    def test_docref_web_variant(self):
        d = ait.build_model_card_docref("mc-1", "https://example.org/c.html")
        assert d["type"]["coding"][0]["code"] == "AIModelCard"
        assert d["content"][0]["attachment"]["url"] == "https://example.org/c.html"
        assert "data" not in d["content"][0]["attachment"]


class TestAIProvenance:
    def test_provenance_shape(self):
        p = ait.build_ai_provenance(
            prov_uid="p-1",
            targets=[{"reference": "urn:uuid:cp"}],
            device_urn="urn:uuid:dev",
            recorded="2026-01-01T00:00:00+00:00",
            occurred="2026-01-01T00:00:00+00:00",
        )
        assert p["meta"]["profile"] == [ait.AI_PROVENANCE_PROFILE]
        assert p["reason"][0]["coding"][0]["code"] == "AIAST"
        assert p["occurredDateTime"] == "2026-01-01T00:00:00+00:00"
        agent = p["agent"][0]
        assert agent["type"]["coding"][0]["code"] == "author"
        assert agent["role"][0]["coding"][0]["code"] == "Artificial-Intelligence"
        assert agent["who"]["reference"] == "urn:uuid:dev"

    def test_human_agents_appended(self):
        human = {"type": {"coding": [{"code": "verifier"}]}, "who": {"display": "Dr X"}}
        p = ait.build_ai_provenance(
            prov_uid="p-1",
            targets=[{"reference": "urn:uuid:cp"}],
            device_urn="urn:uuid:dev",
            recorded="t",
            occurred="t",
            human_agents=[human],
        )
        assert len(p["agent"]) == 2
        assert p["agent"][1]["who"]["display"] == "Dr X"


def _conflict() -> ConflictEntry:
    return ConflictEntry(
        id="conf-x",
        category=ConflictCategory.OVERLAP,
        severity=ConflictSeverity.INFO,
        status=ConflictStatus.DETECTED,
        description="two diets",
        rationale="both recommend a healthy diet",
        suggested_resolution="Combine the two dietary-counseling activities into one",
        confidence="low",
        activity_indices=[0, 2],
        sources=[ConflictSource(cpg_id="A", recommendation_id="r1", excerpt="diet")],
    )


class TestConflictProvenance:
    def test_inline_activity_uses_targetpath(self):
        # index 0 is standalone (in map); index 2 is inline (not in map).
        prov = ait.build_conflict_provenance(
            prov_uid="cp-1",
            conflict=_conflict(),
            careplan_urn="urn:uuid:cp",
            goal_urns=[],
            activity_urn_map={0: "urn:uuid:med0"},
            device_urn="urn:uuid:dev",
            recorded="t",
            occurred="t",
        )
        targets = prov["target"]
        assert {"reference": "urn:uuid:med0"} in targets
        inline = [t for t in targets if t.get("extension")]
        assert len(inline) == 1
        assert inline[0]["extension"][0]["valueString"] == "CarePlan.activity[2].detail"

    def test_extensions_and_note(self):
        prov = ait.build_conflict_provenance(
            prov_uid="cp-1",
            conflict=_conflict(),
            careplan_urn="urn:uuid:cp",
            goal_urns=[],
            activity_urn_map={0: "urn:uuid:med0"},
            device_urn="urn:uuid:dev",
            recorded="t",
            occurred="t",
        )
        urls = {e["url"] for e in prov["extension"]}
        assert f"{ait.ACP_EXT_BASE}/conflict-id" in urls
        assert ait.AICONFIDENCE_EXT in urls  # confidence="low"
        assert prov["note"][0]["authorReference"]["reference"] == "urn:uuid:dev"
        # F16b: suggested_resolution rides its own extension (advisory string).
        sug = next(
            e for e in prov["extension"]
            if e["url"] == f"{ait.ACP_EXT_BASE}/conflict-suggested-resolution"
        )
        assert sug["valueString"] == "Combine the two dietary-counseling activities into one"

    def test_no_suggested_resolution_omits_extension(self):
        c = _conflict()
        c.suggested_resolution = None
        prov = ait.build_conflict_provenance(
            prov_uid="cp-1",
            conflict=c,
            careplan_urn="urn:uuid:cp",
            goal_urns=[],
            activity_urn_map={0: "urn:uuid:med0"},
            device_urn="urn:uuid:dev",
            recorded="t",
            occurred="t",
        )
        urls = {e["url"] for e in prov["extension"]}
        assert f"{ait.ACP_EXT_BASE}/conflict-suggested-resolution" not in urls

    def test_falls_back_to_careplan_when_no_targets(self):
        c = _conflict()
        c.activity_indices = []
        c.goal_indices = []
        prov = ait.build_conflict_provenance(
            prov_uid="cp-1",
            conflict=c,
            careplan_urn="urn:uuid:cp",
            goal_urns=[],
            activity_urn_map={},
            device_urn="urn:uuid:dev",
            recorded="t",
            occurred="t",
        )
        assert prov["target"] == [{"reference": "urn:uuid:cp"}]


class TestSourceDisplayRoundTrip:
    def test_full(self):
        d = ait._source_display("SYN-HTN", "rec-1", "target <140/90")
        assert ait.parse_source_display(d) == {
            "cpgId": "SYN-HTN",
            "recommendationId": "rec-1",
            "excerpt": "target <140/90",
        }

    def test_cpg_only(self):
        d = ait._source_display("SYN-HTN", None, None)
        assert ait.parse_source_display(d) == {"cpgId": "SYN-HTN"}

    def test_identifier_is_authoritative_for_rec(self):
        # display carries no rec, but the entity identifier does.
        d = ait._source_display("SYN-HTN", None, "quote")
        parsed = ait.parse_source_display(d, rec_from_identifier="rec-99")
        assert parsed["recommendationId"] == "rec-99"
        assert parsed["excerpt"] == "quote"

    def test_excerpt_with_em_dash_inside(self):
        # excerpt itself may contain " — "; only the first split matters.
        d = ait._source_display("C", "r", "a — b — c")
        assert ait.parse_source_display(d)["excerpt"] == "a — b — c"


class TestConflictProvenanceReadBack:
    def _prov(self):
        return ait.build_conflict_provenance(
            prov_uid="cp-1",
            conflict=_conflict(),
            careplan_urn="urn:uuid:cp",
            goal_urns=[],
            activity_urn_map={0: "urn:uuid:med0"},
            device_urn="urn:uuid:dev",
            recorded="t",
            occurred="t",
        )

    def test_is_conflict_provenance(self):
        assert ait.is_conflict_provenance(self._prov()) is True

    def test_non_conflict_provenance(self):
        plain = ait.build_ai_provenance(
            prov_uid="p", targets=[{"reference": "urn:uuid:cp"}],
            device_urn="urn:uuid:dev", recorded="t", occurred="t",
        )
        assert ait.is_conflict_provenance(plain) is False

    def test_round_trip_scalars(self):
        pc = ait.plan_conflict_from_provenance(self._prov())
        assert pc["id"] == "conf-x"
        assert pc["description"] == "two diets"
        assert pc["severity"] == "info"
        assert pc["category"] == "overlap"
        assert pc["status"] == "detected"
        assert pc["confidence"] == "low"
        assert pc["suggestedResolution"] == "Combine the two dietary-counseling activities into one"

    def test_round_trip_sources(self):
        pc = ait.plan_conflict_from_provenance(self._prov())
        assert pc["sources"] == [
            {"cpgId": "A", "recommendationId": "r1", "excerpt": "diet"},
        ]

    def test_returns_none_for_non_conflict(self):
        plain = ait.build_ai_provenance(
            prov_uid="p", targets=[{"reference": "urn:uuid:cp"}],
            device_urn="urn:uuid:dev", recorded="t", occurred="t",
        )
        assert ait.plan_conflict_from_provenance(plain) is None
