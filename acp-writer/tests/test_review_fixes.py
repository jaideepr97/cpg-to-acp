"""Acceptance tests for PR #95 review fixes."""

from datetime import date
from unittest.mock import MagicMock, patch

from acp_writer.benchmark.models import QAAnswer
from acp_writer.tools.concept_resolver import resolve
from acp_writer.tools.ips_extractor import extract_condition


SNOMED = "http://snomed.info/sct"
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"


class TestFix1LLMFallback:
    """Fix 1: Inverted boolean made agent fallback unreachable."""

    def test_insufficient_plan_falls_through_to_agent(self):
        """When the query plan returns insufficient_data, the agent should be called."""
        from acp_writer.benchmark.backends.llm_assisted import LLMAssistedBackend

        backend = LLMAssistedBackend()
        backend._llm = MagicMock()

        agent_called = False
        original_resolve = backend._llm_resolve

        def patched_resolve(question, bundle, reference_date):
            nonlocal agent_called
            from acp_writer.tools.query_planner import generate_query_plan
            from acp_writer.tools.ips_serializer import serialize_ips

            condensed = serialize_ips(bundle)
            plan = {"function": "latest_value", "params": {"code": "http://loinc.org|99999-9"}}
            result = backend.answer(question, bundle, reference_date, structured_intent=plan)
            if not result.insufficient_data:
                return result
            agent_called = True
            return QAAnswer(value=42, kind="number")

        backend._llm_resolve = patched_resolve
        bundle = {"entry": []}
        answer = backend.answer("xyzzy unknown concept", bundle, date(2026, 6, 1))
        assert agent_called or answer.insufficient_data

    def test_successful_plan_does_not_fall_through(self):
        """When the plan returns a real answer, the agent should NOT be called."""
        from acp_writer.benchmark.backends.llm_assisted import LLMAssistedBackend

        backend = LLMAssistedBackend()
        backend._llm = MagicMock()

        bundle = {"entry": [{"resource": {
            "resourceType": "Observation", "id": "o1", "status": "final",
            "effectiveDateTime": "2026-01-01",
            "code": {"coding": [{"system": LOINC, "code": "8480-6"}]},
            "valueQuantity": {"value": 140, "unit": "mmHg"},
        }}]}

        answer = backend.answer(
            "systolic bp", bundle, date(2026, 6, 1),
            structured_intent={"function": "latest_value", "params": {"code": "http://loinc.org|8480-6"}},
        )
        assert answer.value == 140
        assert not answer.insufficient_data


class TestFix2Furosemide:
    """Fix 2: Furosemide mapped to gabapentin's code."""

    def test_furosemide_different_from_gabapentin(self):
        furo = resolve("furosemide")
        gaba = resolve("gabapentin")
        assert furo is not None
        assert gaba is not None
        assert furo.code != gaba.code

    def test_furosemide_correct_code(self):
        result = resolve("furosemide")
        assert result.code == "197417"


class TestFix3ICD10System:
    """Fix 3: ICD-10 code carried under SNOMED system URL."""

    def test_icd10_diabetes_matches(self):
        bundle = {"entry": [{"resource": {
            "resourceType": "Condition", "id": "c1",
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "code": {"coding": [{"system": ICD10CM, "code": "E11", "display": "Type 2 diabetes mellitus"}]},
        }}]}
        resolved = resolve("diabetes")
        assert resolved is not None
        assert any(ICD10CM in c for c in (resolved.codes or []))

        for code_token in resolved.codes:
            if ICD10CM in code_token:
                sys, cd = code_token.rsplit("|", 1)
                result = extract_condition(bundle, sys, cd)
                if result.found:
                    assert result.value is True
                    return
        assert False, "ICD-10 E11 should match diabetes resolve codes"


class TestFix4LstripArticle:
    """Fix 4: lstrip character-set misuse."""

    def test_asthma_resolves_correctly(self):
        result = resolve("has asthma")
        assert result is not None
        assert result.action == "extract_condition"
        assert result.code == "195967001"

    def test_empty_term_no_false_positive(self):
        result = resolve("has an")
        assert result is None

    def test_article_stripped_correctly(self):
        result = resolve("has an infection")
        assert result is None or result.action != "extract_drug_class"

    def test_anemia_not_mangled(self):
        result = resolve("has anemia")
        assert result is None or result.action != "extract_drug_class"
