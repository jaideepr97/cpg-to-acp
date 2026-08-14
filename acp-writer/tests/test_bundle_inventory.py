"""Tests for bundle code inventory."""

import json
from pathlib import Path

from acp_writer.tools.bundle_inventory import build_bundle_inventory

PROJECT_ROOT = Path(__file__).parent.parent.parent
BUNDLES_DIR = PROJECT_ROOT / "acp-writer" / "benchmarks" / "bundles"

ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"


def _load(name: str) -> dict:
    return json.loads((BUNDLES_DIR / name).read_text())


class TestMessyDataInventory:
    def test_contains_icd10_condition(self):
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)
        conditions = inventory.conditions()
        icd10_entries = [e for e in conditions if e.system == ICD10CM]
        assert len(icd10_entries) >= 1
        displays = [e.display.lower() for e in icd10_entries]
        assert any("hypothyroidism" in d for d in displays)

    def test_contains_free_text_medication(self):
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)
        meds = inventory.medications()
        free_text = [e for e in meds if not e.system and e.text]
        assert len(free_text) >= 1
        assert any("levothyroxine" in (e.text or "").lower() for e in free_text)

    def test_contains_wrong_loinc_observation(self):
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)
        obs = inventory.observations()
        tsh_entries = [e for e in obs if "thyroid" in (e.display or "").lower()]
        assert len(tsh_entries) >= 1

    def test_inventory_count(self):
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)
        assert len(inventory.entries) > 10

    def test_render_for_llm(self):
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)
        rendered = inventory.render_for_llm()
        assert "Condition" in rendered
        assert "Medications" in rendered
        assert "Observation" in rendered
        assert len(rendered) < 5000


class TestComplexPatientInventory:
    def test_all_resource_types_present(self):
        bundle = _load("complex-patient-01.json")
        inventory = build_bundle_inventory(bundle)
        types = {e.resource_type for e in inventory.entries}
        assert "Condition" in types
        assert "Observation" in types
        assert "AllergyIntolerance" in types

    def test_code_tokens_unique(self):
        bundle = _load("complex-patient-01.json")
        inventory = build_bundle_inventory(bundle)
        tokens = inventory.all_code_tokens()
        assert len(tokens) > 5
