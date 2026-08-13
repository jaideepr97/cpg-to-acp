"""Tests for answer guardrails — choke point, answer-type contracts, calibration.

Covers F1-F5 (structural), C1-C3 (calibration), D1-D3 (type-aware layering).
"""

from unittest.mock import patch
from acp_writer.benchmark.models import QAAnswer
from acp_writer.tools.answer_guardrails import (
    verify_answer,
    check_definitive_miss,
    classify_answer,
    _check_provenance_required,
    _check_value_consistency,
    _check_concept_consistency,
    _check_conflict,
    _check_absence_with_ledger,
    _value_in_resource,
)
from acp_writer.tools.bundle_inventory import BundleInventory, InventoryEntry, build_bundle_inventory

LOINC = "http://loinc.org"


def _make_bundle(*observations, conditions=None, meds=None):
    entries = []
    for obs in observations:
        entries.append({"resource": obs})
    for cond in (conditions or []):
        entries.append({"resource": cond})
    for med in (meds or []):
        entries.append({"resource": med})
    return {"resourceType": "Bundle", "entry": entries}


def _obs(obs_id, system, code, display, value, date_str="2026-04-01"):
    return {
        "resourceType": "Observation", "id": obs_id,
        "code": {"coding": [{"system": system, "code": code, "display": display}]},
        "valueQuantity": {"value": value, "unit": "mmHg"},
        "effectiveDateTime": date_str,
    }


# --- D1: Question intent classification ---

class TestQuestionIntent:
    def test_boolean_is_detected(self):
        from acp_writer.benchmark.backends.llm_assisted import question_intent
        assert question_intent("Is the patient on GDMT?") == "boolean"
        assert question_intent("Does the patient have diabetes?") == "boolean"
        assert question_intent("Should anticoagulation continue?") == "boolean"
        assert question_intent("Has the patient had a stroke?") == "boolean"
        assert question_intent("Are there any untreated conditions?") == "boolean"

    def test_numeric_is_detected(self):
        from acp_writer.benchmark.backends.llm_assisted import question_intent
        assert question_intent("What is the patient's TSH level?") == "numeric"
        assert question_intent("How many active conditions?") == "numeric"

    def test_open_fallback(self):
        from acp_writer.benchmark.backends.llm_assisted import question_intent
        assert question_intent("List all medications") == "open"


class TestD1IntentMismatchFallthrough:
    """D1: numeric answer to boolean-intent question falls through to agent."""

    def test_query_plan_numeric_for_boolean_falls_through(self):
        from acp_writer.benchmark.backends.llm_assisted import LLMAssistedBackend, question_intent
        from unittest.mock import MagicMock, patch
        from datetime import date

        assert question_intent("Is the patient's LDL at goal?") == "boolean"

        backend = LLMAssistedBackend()
        backend._llm = MagicMock()

        agent_called = False

        def mock_agent(q, b, rd, llm, extra_context=None):
            nonlocal agent_called
            agent_called = True
            return {"answer": True, "provenance": ["Obs/ldl"], "insufficient_data": False, "tool_ledger": [
                {"type": "lookup_observation", "found": True, "definitive_miss": False}
            ]}

        bundle = _make_bundle(_obs("ldl", LOINC, "2089-1", "LDL", 62))

        with patch("acp_writer.benchmark.backends.llm_assisted.generate_query_plan",
                   return_value={"function": "latest_value", "params": {"code": f"{LOINC}|2089-1"}}), \
             patch("acp_writer.tools.qa_agent.agent_answer", side_effect=mock_agent):
            result = backend.answer("Is the patient's LDL at goal?", bundle, date(2026, 6, 1))

        assert agent_called, "Agent should have been called after intent mismatch"

    def test_intent_type_mismatch_downgrades_at_choke(self):
        """Numeric answer that survives to choke point for boolean question → downgrade."""
        answer = QAAnswer(value=62, kind="number", provenance=["Obs/ldl"])
        bundle = _make_bundle()
        inventory = BundleInventory()

        result = verify_answer(answer, "Is LDL at goal?", bundle, inventory, question_intent="boolean")
        assert result.resolution_basis and "boolean_presence" in result.resolution_basis


# --- D2: Scoring v2 ---

class TestScoringV2:
    def test_genuine_boolean_correct(self):
        from acp_writer.benchmark.scoring import _compare_values
        assert _compare_values("boolean", True, True, 0.0) is True
        assert _compare_values("boolean", False, False, 0.0) is True

    def test_numeric_as_boolean_incorrect(self):
        from acp_writer.benchmark.scoring import _compare_values
        assert _compare_values("boolean", True, 62, 0.0) is False
        assert _compare_values("boolean", True, 5.1, 0.0) is False

    def test_zero_as_false_incorrect(self):
        from acp_writer.benchmark.scoring import _compare_values
        assert _compare_values("boolean", False, 0, 0.0) is False

    def test_none_is_incorrect(self):
        from acp_writer.benchmark.scoring import _compare_values
        assert _compare_values("boolean", True, None, 0.0) is False


# --- D3: On-demand negative evidence ---

class TestD3OnDemandAbsence:
    @patch("acp_writer.tools.answer_guardrails._on_demand_absence_check", return_value="definitive_miss")
    def test_false_no_ledger_pipeline_confirms_absence(self, mock_check):
        answer = QAAnswer(value=False, kind="boolean", provenance=[])
        inventory = BundleInventory()
        result = _check_absence_with_ledger(answer, [], "Is the patient missing antiplatelet therapy?", inventory)
        assert not result.insufficient_data
        assert result.value is False
        mock_check.assert_called_once()

    @patch("acp_writer.tools.answer_guardrails._on_demand_absence_check", return_value="present")
    def test_false_but_pipeline_finds_present_downgrades(self, mock_check):
        answer = QAAnswer(value=False, kind="boolean", provenance=[])
        inventory = BundleInventory()
        result = _check_absence_with_ledger(answer, [], "Is the patient missing statins?", inventory)
        assert result.insufficient_data
        assert "absence_contradicted" in (result.error or "")

    @patch("acp_writer.tools.answer_guardrails._on_demand_absence_check", return_value="unresolved")
    def test_false_pipeline_unresolved_downgrades(self, mock_check):
        answer = QAAnswer(value=False, kind="boolean", provenance=[])
        inventory = BundleInventory()
        result = _check_absence_with_ledger(answer, [], "Is the patient missing X?", inventory)
        assert result.insufficient_data

    def test_false_with_ledger_definitive_miss_passes(self):
        answer = QAAnswer(value=False, kind="boolean", provenance=[])
        ledger = [{"type": "check_condition", "found": False, "definitive_miss": True}]
        result = _check_absence_with_ledger(answer, ledger)
        assert not result.insufficient_data

    def test_false_ledger_shows_found_downgrades(self):
        answer = QAAnswer(value=False, kind="boolean", provenance=[])
        ledger = [{"type": "check_condition", "found": True, "definitive_miss": False}]
        result = _check_absence_with_ledger(answer, ledger)
        assert result.insufficient_data


# --- Answer classification ---

class TestAnswerClassification:
    def test_numeric_retrieval(self):
        assert classify_answer(QAAnswer(value=142.0, kind="number")) == "numeric_retrieval"

    def test_boolean_presence(self):
        assert classify_answer(QAAnswer(value=True, kind="boolean", provenance=["C/1"])) == "boolean_presence"

    def test_boolean_absence_no_provenance(self):
        assert classify_answer(QAAnswer(value=False, kind="boolean", provenance=[])) == "boolean_absence"

    def test_boolean_intent_overrides_numeric_value(self):
        """A numeric answer classified under boolean intent → boolean contract."""
        assert classify_answer(
            QAAnswer(value=62, kind="number", provenance=["Obs/1"]),
            question_intent="boolean",
        ) == "boolean_presence"

    def test_insufficient(self):
        assert classify_answer(QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)) == "insufficient"


# --- C1: value-consistency excludes booleans ---

class TestC1ValueConsistency:
    def test_boolean_true_skipped(self):
        answer = QAAnswer(value=True, kind="boolean", provenance=["C/1"])
        result = _check_value_consistency(answer, _make_bundle())
        assert result.value is True

    def test_boolean_false_skipped(self):
        answer = QAAnswer(value=False, kind="boolean", provenance=["C/1"])
        result = _check_value_consistency(answer, _make_bundle())
        assert result.value is False


# --- C2: concept-consistency numeric only ---

class TestC2ConceptConsistency:
    @patch("acp_writer.tools.answer_guardrails._get_terminology_candidates")
    def test_hba1c_for_hemoglobin_downgrades(self, mock_term):
        mock_term.return_value = {f"{LOINC}|718-7"}
        answer = QAAnswer(value=7.4, kind="number", provenance=["Observation/hba1c"])
        inventory = BundleInventory(entries=[
            InventoryEntry(resource_type="Observation", fhir_reference="Observation/hba1c",
                          system=LOINC, code="4548-4", display="Hemoglobin A1c"),
        ])
        result = _check_concept_consistency(answer, "hemoglobin", inventory)
        assert result.insufficient_data

    def test_boolean_skips_concept_check(self):
        answer = QAAnswer(value=True, kind="boolean", provenance=["Med/1", "Med/2"])
        inventory = BundleInventory(entries=[
            InventoryEntry(resource_type="MedicationRequest", fhir_reference="Med/1",
                          system="rxnorm", code="861004", display="Metformin"),
        ])
        result = _check_concept_consistency(answer, "Is patient on GDMT?", inventory)
        assert not result.insufficient_data


# --- F2: fail closed ---

class TestF2FailClosed:
    def test_nonexistent_ref_fails(self):
        assert not _value_in_resource(142.0, "Observation/nope", _make_bundle())

    def test_found_value_passes(self):
        obs = _obs("bp-1", LOINC, "8480-6", "SBP", 142)
        assert _value_in_resource(142.0, "Observation/bp-1", _make_bundle(obs))


# --- F4: mechanical refusal ---

class TestF4MechanicalRefusal:
    def test_all_miss_overrides_true(self):
        ledger = [{"type": "check_condition", "found": False, "definitive_miss": True}]
        result = check_definitive_miss(ledger, QAAnswer(value=True, kind="boolean", answered_by="agent"))
        assert result.value is False
        assert result.answered_by == "guardrail_downgrade"


# --- F5: conflict ---

class TestF5Conflict:
    def test_conflicting_values_downgrade(self):
        obs_a = _obs("k-a", LOINC, "2823-3", "K", 4.1, "2026-04-01T08:00")
        obs_b = _obs("k-b", LOINC, "2823-3", "K", 4.8, "2026-04-01T08:30")
        bundle = _make_bundle(obs_a, obs_b)
        inventory = build_bundle_inventory(bundle)
        answer = QAAnswer(value=4.1, kind="number", provenance=["Observation/k-a"])
        result = _check_conflict(answer, bundle, inventory)
        assert result.insufficient_data


# --- End-to-end ---

class TestEndToEnd:
    @patch("acp_writer.tools.answer_guardrails._get_terminology_candidates")
    def test_hemoglobin_hba1c_caught(self, mock_term):
        mock_term.return_value = {f"{LOINC}|718-7"}
        obs = _obs("hba1c", LOINC, "4548-4", "Hemoglobin A1c", 7.4)
        bundle = _make_bundle(obs)
        inventory = build_bundle_inventory(bundle)
        answer = QAAnswer(value=7.4, kind="number", provenance=["Observation/hba1c"], answered_by="query_plan")
        result = verify_answer(answer, "hemoglobin", bundle, inventory)
        assert result.insufficient_data
        assert result.answered_by == "guardrail_downgrade"

    @patch("acp_writer.tools.answer_guardrails._get_terminology_candidates")
    def test_valid_numeric_passes(self, mock_term):
        mock_term.return_value = {f"{LOINC}|8480-6"}
        obs = _obs("bp-1", LOINC, "8480-6", "SBP", 142)
        bundle = _make_bundle(obs)
        inventory = build_bundle_inventory(bundle)
        answer = QAAnswer(value=142.0, kind="number", provenance=["Observation/bp-1"], answered_by="resolver")
        result = verify_answer(answer, "systolic bp", bundle, inventory)
        assert result.value == 142.0

    def test_boolean_true_with_provenance_passes(self):
        cond = {"resourceType": "Condition", "id": "c1",
                "code": {"coding": [{"system": "http://snomed.info/sct", "code": "44054006", "display": "Diabetes"}]},
                "clinicalStatus": {"coding": [{"code": "active"}]}}
        bundle = _make_bundle(conditions=[cond])
        inventory = build_bundle_inventory(bundle)
        answer = QAAnswer(value=True, kind="boolean", provenance=["Condition/c1"], answered_by="resolver")
        result = verify_answer(answer, "diabetes", bundle, inventory)
        assert result.value is True

    def test_verification_class_logged(self):
        obs = _obs("bp-1", LOINC, "8480-6", "SBP", 142)
        bundle = _make_bundle(obs)
        inventory = build_bundle_inventory(bundle)
        answer = QAAnswer(value=142.0, kind="number", provenance=["Observation/bp-1"])
        with patch("acp_writer.tools.answer_guardrails._get_terminology_candidates") as m:
            m.return_value = {f"{LOINC}|8480-6"}
            result = verify_answer(answer, "systolic bp", bundle, inventory)
        assert "verification_class:numeric_retrieval" in (result.resolution_basis or "")
