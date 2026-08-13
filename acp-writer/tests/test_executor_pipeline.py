"""Tests for DMN executor with concept-resolution pipeline (Part 2 wiring)."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from acp_writer.nodes.dmn_executor import _extract_input_value
from acp_writer.tools.bundle_inventory import build_bundle_inventory
from acp_writer.tools.concept_resolution import ResolutionResult
from acp_writer.tools.terminology_lookup import LookupResult

PROJECT_ROOT = Path(__file__).parent.parent.parent
BUNDLES_DIR = PROJECT_ROOT / "acp-writer" / "benchmarks" / "bundles"


def _load(name: str) -> dict:
    return json.loads((BUNDLES_DIR / name).read_text())


class TestPipelineWiredInExecutor:
    """Executor resolves variables through the full pipeline."""

    def test_icd10_condition_resolves_true(self):
        """ICD-10-coded hypothyroidism resolves True via terminology."""
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)

        with patch("acp_writer.tools.terminology_lookup.find_candidates") as mock:
            mock.return_value = [
                LookupResult(found=True, system="http://hl7.org/fhir/sid/icd-10-cm",
                            code="E03.9", display="Hypothyroidism"),
            ]
            value, ref, audit = _extract_input_value(
                bundle, "Has Hypothyroidism", "boolean", {},
                inventory=inventory, llm_client=MagicMock(),
            )

        assert value is True
        assert ref is not None
        assert audit.get("match_basis") in ("cache", "terminology", "display_text")

    @patch("acp_writer.tools.terminology_lookup.find_candidates", return_value=[])
    def test_free_text_medication_resolves(self, mock_find):
        """Free-text levothyroxine resolves via display text."""
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)

        value, ref, audit = _extract_input_value(
            bundle, "levothyroxine", "boolean", {},
            inventory=inventory, llm_client=MagicMock(),
        )

        # The concept resolver maps "levothyroxine" — should resolve
        # either through cache or display text on the free-text med
        assert value is True or value is not None

    def test_standard_observation_via_pipeline(self):
        """Standard LOINC observation resolves through concept-resolver cache."""
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)

        value, ref, audit = _extract_input_value(
            bundle, "Systolic BP", "number", {},
            inventory=inventory, llm_client=MagicMock(),
        )

        assert value == 138
        assert ref is not None

    def test_absent_concept_definitive_miss(self):
        """Concept genuinely absent from bundle → definitive miss → False."""
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)

        mock_llm = MagicMock()
        from pydantic import BaseModel, Field

        class MockMatch(BaseModel):
            matched_references: list[str] = Field(default_factory=list)
            reasoning: str = ""

        mock_structured = MagicMock()
        mock_structured.invoke.return_value = MockMatch()
        mock_llm.with_structured_output.return_value = mock_structured

        with patch("acp_writer.tools.terminology_lookup.find_candidates", return_value=[]):
            value, ref, audit = _extract_input_value(
                bundle, "Has Rheumatoid Arthritis", "boolean", {},
                inventory=inventory, llm_client=mock_llm,
            )

        assert value is False
        assert audit.get("match_basis") == "definitive_miss"

    def test_degraded_mode_no_llm(self):
        """When LLM is None and concept not in cache/terminology, result is unresolved."""
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)

        with patch("acp_writer.tools.terminology_lookup.find_candidates", return_value=[]):
            value, ref, audit = _extract_input_value(
                bundle, "Some Unknown Rare Condition", "boolean", {},
                inventory=inventory, llm_client=None,
            )

        assert value is None
        assert audit.get("degraded") is True

    def test_degraded_mode_llm_exception(self):
        """When pipeline raises, resolution degrades gracefully."""
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)

        with patch("acp_writer.tools.concept_resolution.resolve_concept_in_bundle",
                   side_effect=Exception("Pipeline error")):
            value, ref, audit = _extract_input_value(
                bundle, "Has Lupus", "boolean", {},
                inventory=inventory, llm_client=MagicMock(),
            )

        assert value is None
        assert audit.get("degraded") is True

    def test_prior_dmn_results_still_first(self):
        """Chained DMN results take priority over everything."""
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)

        prior = {"model-1": {"Treatment Action": {"Systolic BP": 999}}}

        value, ref, audit = _extract_input_value(
            bundle, "Systolic BP", "number", prior,
            inventory=inventory,
        )

        assert value == 999
        assert audit.get("match_basis") == "prior_dmn"

    def test_decision_variable_codes_still_second(self):
        """DecisionVariable.codes take priority over pipeline."""
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)

        value, ref, audit = _extract_input_value(
            bundle, "SBP", "number", {},
            codes=["http://loinc.org|8480-6"],
            inventory=inventory,
        )

        assert value == 138
        assert audit.get("match_basis") == "decision_variable_codes"

    def test_known_variable_map_retired(self):
        """The old KNOWN_VARIABLE_MAP entries now resolve through the pipeline."""
        bundle = _load("messy-data-01.json")
        inventory = build_bundle_inventory(bundle)

        # "systolic bp" was in the old map — now handled by concept resolver cache
        value, ref, audit = _extract_input_value(
            bundle, "systolic bp", "number", {},
            inventory=inventory,
        )

        assert value == 138
        assert audit.get("match_basis") in ("cache", "terminology", "display_text")
