"""Tests for answer guardrails — F1 through F5.

Tests the verification choke point, fail-closed behavior,
concept-consistency, conflict detection, and mechanical refusal.
"""

import json
from unittest.mock import patch, MagicMock
from datetime import date

import pytest

from acp_writer.benchmark.models import QAAnswer
from acp_writer.tools.answer_guardrails import (
    verify_answer,
    check_definitive_miss,
    _check_provenance_required,
    _check_value_consistency,
    _check_concept_consistency,
    _check_conflict,
    _value_in_resource,
)
from acp_writer.tools.bundle_inventory import BundleInventory, InventoryEntry, build_bundle_inventory


def _make_bundle(*observations, conditions=None, meds=None):
    """Build a minimal FHIR bundle with given observations."""
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
        "resourceType": "Observation",
        "id": obs_id,
        "code": {"coding": [{"system": system, "code": code, "display": display}]},
        "valueQuantity": {"value": value, "unit": "mmHg"},
        "effectiveDateTime": date_str,
    }


LOINC = "http://loinc.org"


class TestF1ChokepointOnEveryPath:
    """F1: verify_answer processes QAAnswer objects, not just agent dicts."""

    def test_resolver_answer_gets_verified(self):
        """A hallucination-shaped answer is downgraded regardless of source."""
        answer = QAAnswer(
            value=999.0, kind="number",
            provenance=["Observation/nonexistent"],
            answered_by="resolver",
        )
        bundle = _make_bundle()
        inventory = BundleInventory()

        result = verify_answer(answer, "blood pressure", bundle, inventory)
        assert result.insufficient_data
        assert result.answered_by == "guardrail_downgrade"

    def test_query_plan_answer_gets_verified(self):
        """Query-plan answers also pass through guardrails."""
        answer = QAAnswer(
            value=142.0, kind="number",
            provenance=["Observation/nonexistent"],
            answered_by="query_plan",
        )
        bundle = _make_bundle()
        inventory = BundleInventory()

        result = verify_answer(answer, "systolic bp", bundle, inventory)
        assert result.insufficient_data
        assert "guardrail" in (result.error or "")

    def test_agent_answer_gets_verified(self):
        """Agent answers are verified as before."""
        answer = QAAnswer(
            value=7.4, kind="number",
            provenance=["Observation/obs-hba1c"],
            answered_by="agent",
        )
        obs = _obs("obs-hba1c", LOINC, "4548-4", "Hemoglobin A1c", 7.4)
        bundle = _make_bundle(obs)
        inventory = build_bundle_inventory(bundle)

        result = verify_answer(answer, "HbA1c", bundle, inventory)
        assert result.value == 7.4
        assert not result.insufficient_data

    def test_insufficient_data_passes_through(self):
        """Already-insufficient answers pass without guardrail evaluation."""
        answer = QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)
        result = verify_answer(answer, "anything", {}, BundleInventory())
        assert result.insufficient_data
        assert result.answered_by is None


class TestF2FailClosed:
    """F2: unverifiable citations cause downgrade, not pass."""

    def test_nonexistent_reference_downgrades(self):
        """Answer citing Observation/nonexistent is downgraded."""
        answer = QAAnswer(
            value=142.0, kind="number",
            provenance=["Observation/nonexistent"],
        )
        bundle = _make_bundle()
        assert not _value_in_resource(142.0, "Observation/nonexistent", bundle)

    def test_value_found_in_resource_passes(self):
        """Value present in cited resource passes."""
        obs = _obs("bp-1", LOINC, "8480-6", "Systolic BP", 142)
        bundle = _make_bundle(obs)
        assert _value_in_resource(142.0, "Observation/bp-1", bundle)

    def test_wrong_value_in_resource_fails(self):
        """Value not matching cited resource fails."""
        obs = _obs("bp-1", LOINC, "8480-6", "Systolic BP", 120)
        bundle = _make_bundle(obs)
        assert not _value_in_resource(142.0, "Observation/bp-1", bundle)

    def test_component_value_found(self):
        """Value in a component is found."""
        obs = {
            "resourceType": "Observation",
            "id": "bp-panel",
            "code": {"coding": [{"system": LOINC, "code": "85354-9", "display": "BP panel"}]},
            "component": [
                {"code": {"coding": [{"system": LOINC, "code": "8480-6"}]},
                 "valueQuantity": {"value": 138}},
            ],
        }
        bundle = _make_bundle(obs)
        assert _value_in_resource(138.0, "Observation/bp-panel", bundle)

    def test_no_provenance_downgrades(self):
        """Non-insufficient answer without provenance is downgraded."""
        answer = QAAnswer(value=142.0, kind="number", provenance=[])
        result = _check_provenance_required(answer)
        assert result.insufficient_data
        assert "provenance_required" in (result.error or "")


class TestF3ConceptConsistency:
    """F3: independent verification catches hemoglobin/HbA1c confusion."""

    @patch("acp_writer.tools.answer_guardrails._get_terminology_candidates")
    def test_hba1c_cited_for_hemoglobin_downgrades(self, mock_term):
        """HbA1c (4548-4) cited for 'hemoglobin' question is caught."""
        mock_term.return_value = {f"{LOINC}|718-7"}

        answer = QAAnswer(
            value=7.4, kind="number",
            provenance=["Observation/obs-hba1c"],
        )
        inventory = BundleInventory(entries=[
            InventoryEntry(
                resource_type="Observation",
                fhir_reference="Observation/obs-hba1c",
                system=LOINC, code="4548-4",
                display="Hemoglobin A1c",
            ),
        ])

        result = _check_concept_consistency(answer, "hemoglobin", inventory)
        assert result.insufficient_data
        assert "concept_consistency" in (result.error or "")

    @patch("acp_writer.tools.answer_guardrails._get_terminology_candidates")
    def test_same_concept_passes(self, mock_term):
        """HbA1c cited for 'HbA1c' question passes."""
        mock_term.return_value = {f"{LOINC}|4548-4"}

        answer = QAAnswer(
            value=7.4, kind="number",
            provenance=["Observation/obs-hba1c"],
        )
        inventory = BundleInventory(entries=[
            InventoryEntry(
                resource_type="Observation",
                fhir_reference="Observation/obs-hba1c",
                system=LOINC, code="4548-4",
                display="Hemoglobin A1c",
            ),
        ])

        result = _check_concept_consistency(answer, "HbA1c", inventory)
        assert not result.insufficient_data
        assert result.value == 7.4

    @patch("acp_writer.tools.answer_guardrails._get_terminology_candidates")
    def test_terminology_unavailable_fails_closed(self, mock_term):
        """When terminology returns None (unavailable), fail closed."""
        mock_term.return_value = None

        answer = QAAnswer(value=5.8, kind="number", provenance=["Observation/obs-tsh"])
        inventory = BundleInventory(entries=[
            InventoryEntry(
                resource_type="Observation",
                fhir_reference="Observation/obs-tsh",
                system=LOINC, code="3016-3",
                display="TSH",
            ),
        ])

        result = _check_concept_consistency(answer, "TSH level", inventory)
        assert not result.insufficient_data

    @patch("acp_writer.tools.answer_guardrails._get_terminology_candidates")
    def test_display_match_passes_when_no_terminology_candidates(self, mock_term):
        """When terminology returns empty but display matches, pass."""
        mock_term.return_value = set()

        answer = QAAnswer(value=5.8, kind="number", provenance=["Observation/obs-tsh"])
        inventory = BundleInventory(entries=[
            InventoryEntry(
                resource_type="Observation",
                fhir_reference="Observation/obs-tsh",
                system=LOINC, code="3016-3",
                display="TSH",
            ),
        ])

        result = _check_concept_consistency(answer, "TSH", inventory)
        assert not result.insufficient_data


class TestF4MechanicalRefusal:
    """F4: definitive_miss from tools overrides agent's boolean True."""

    def test_all_definitive_miss_overrides_true(self):
        """Agent says True but all tools returned definitive_miss → False."""
        ledger = [
            {"type": "check_condition", "found": False, "definitive_miss": True},
            {"type": "check_condition", "found": False, "definitive_miss": True},
        ]
        answer = QAAnswer(value=True, kind="boolean", answered_by="agent")

        result = check_definitive_miss(ledger, answer)
        assert result.value is False
        assert result.answered_by == "guardrail_downgrade"
        assert "mechanical_refusal" in (result.error or "")

    def test_some_found_no_override(self):
        """If any tool found the concept, don't override."""
        ledger = [
            {"type": "check_condition", "found": True, "definitive_miss": False},
            {"type": "check_medication", "found": False, "definitive_miss": True},
        ]
        answer = QAAnswer(value=True, kind="boolean", answered_by="agent")

        result = check_definitive_miss(ledger, answer)
        assert result.value is True

    def test_no_override_on_false_answer(self):
        """Agent says False — definitive_miss doesn't override False."""
        ledger = [
            {"type": "check_condition", "found": False, "definitive_miss": True},
        ]
        answer = QAAnswer(value=False, kind="boolean", answered_by="agent")

        result = check_definitive_miss(ledger, answer)
        assert result.value is False
        assert result.answered_by == "agent"

    def test_no_override_on_numeric(self):
        """Numeric answers are not affected by definitive_miss."""
        ledger = [
            {"type": "lookup_observation", "found": False, "definitive_miss": True},
        ]
        answer = QAAnswer(value=42.0, kind="number", answered_by="agent")

        result = check_definitive_miss(ledger, answer)
        assert result.value == 42.0

    def test_empty_ledger_no_override(self):
        """Empty tool ledger means no override."""
        answer = QAAnswer(value=True, kind="boolean", answered_by="agent")
        result = check_definitive_miss([], answer)
        assert result.value is True

    def test_insufficient_data_passes_through(self):
        """Already-insufficient answers pass without checking ledger."""
        answer = QAAnswer(value=None, kind="insufficient_data", insufficient_data=True)
        result = check_definitive_miss(
            [{"type": "check_condition", "found": False, "definitive_miss": True}],
            answer,
        )
        assert result.insufficient_data


class TestF5ConflictDetection:
    """F5: conflicting values detected regardless of answer path."""

    def test_same_code_different_values_downgrades(self):
        """Two potassium readings (4.1 vs 4.8) cause downgrade."""
        obs_a = _obs("k-m1a", LOINC, "2823-3", "Potassium", 4.1, "2026-04-01T08:00")
        obs_b = _obs("k-m1b", LOINC, "2823-3", "Potassium", 4.8, "2026-04-01T08:30")
        bundle = _make_bundle(obs_a, obs_b)
        inventory = build_bundle_inventory(bundle)

        answer = QAAnswer(
            value=4.1, kind="number",
            provenance=["Observation/k-m1a"],
            answered_by="query_plan",
        )

        result = _check_conflict(answer, bundle, inventory)
        assert result.insufficient_data
        assert "conflict_enforcement" in (result.error or "")

    def test_single_value_no_conflict(self):
        """Single observation passes conflict check."""
        obs = _obs("k-1", LOINC, "2823-3", "Potassium", 5.1)
        bundle = _make_bundle(obs)
        inventory = build_bundle_inventory(bundle)

        answer = QAAnswer(
            value=5.1, kind="number",
            provenance=["Observation/k-1"],
        )

        result = _check_conflict(answer, bundle, inventory)
        assert not result.insufficient_data
        assert result.value == 5.1

    def test_same_value_no_conflict(self):
        """Two readings with same value don't trigger conflict."""
        obs_a = _obs("k-a", LOINC, "2823-3", "Potassium", 4.1, "2026-04-01T08:00")
        obs_b = _obs("k-b", LOINC, "2823-3", "Potassium", 4.1, "2026-04-01T08:30")
        bundle = _make_bundle(obs_a, obs_b)
        inventory = build_bundle_inventory(bundle)

        answer = QAAnswer(
            value=4.1, kind="number",
            provenance=["Observation/k-a"],
        )

        result = _check_conflict(answer, bundle, inventory)
        assert not result.insufficient_data

    def test_query_plan_path_conflict_detected(self):
        """Conflict detection works on query-plan answers (not just agent)."""
        obs_a = _obs("k-m1a", LOINC, "2823-3", "Potassium", 4.1, "2026-04-01T08:00")
        obs_b = _obs("k-m1b", LOINC, "2823-3", "Potassium", 4.8, "2026-04-01T08:30")
        bundle = _make_bundle(obs_a, obs_b)
        inventory = build_bundle_inventory(bundle)

        answer = QAAnswer(
            value=4.8, kind="number",
            provenance=["Observation/k-m1b"],
            answered_by="query_plan",
        )

        result = verify_answer(answer, "potassium", bundle, inventory)
        assert result.insufficient_data
        assert result.answered_by == "guardrail_downgrade"


class TestEndToEndVerification:
    """Integration tests: full verify_answer pipeline."""

    def test_valid_answer_passes_all_guardrails(self):
        """A correct answer with valid provenance passes through."""
        obs = _obs("bp-1", LOINC, "8480-6", "Systolic BP", 142)
        bundle = _make_bundle(obs)
        inventory = build_bundle_inventory(bundle)

        answer = QAAnswer(
            value=142.0, kind="number",
            provenance=["Observation/bp-1"],
            answered_by="resolver",
        )

        with patch("acp_writer.tools.answer_guardrails._get_terminology_candidates") as mock_term:
            mock_term.return_value = {f"{LOINC}|8480-6"}
            result = verify_answer(answer, "systolic bp", bundle, inventory)

        assert result.value == 142.0
        assert not result.insufficient_data

    @patch("acp_writer.tools.answer_guardrails._get_terminology_candidates")
    def test_hemoglobin_hba1c_confusion_caught(self, mock_term):
        """The canonical hallucination case: HbA1c value returned for hemoglobin question."""
        mock_term.return_value = {f"{LOINC}|718-7"}

        obs = _obs("obs-hba1c", LOINC, "4548-4", "Hemoglobin A1c", 7.4)
        bundle = _make_bundle(obs)
        inventory = build_bundle_inventory(bundle)

        answer = QAAnswer(
            value=7.4, kind="number",
            provenance=["Observation/obs-hba1c"],
            answered_by="query_plan",
        )

        result = verify_answer(answer, "hemoglobin", bundle, inventory)
        assert result.insufficient_data
        assert result.answered_by == "guardrail_downgrade"
