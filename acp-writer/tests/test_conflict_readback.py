"""WS6 read-back: conflicts survive the round-trip into the BFF view-model.

Two paths reconstruct a ``PlanConflict`` for the UI:
  1. from the FHIR bundle's conflict Provenances (persisted care plans) —
     ``bff._extract_view_from_bundle``;
  2. from the planning brief's ``ConflictEntry`` (live run detail) —
     ``artifact_resolver.plan_conflict_from_entry``.
Both must yield the same camelCase contract shape.
"""

from acp_writer.planning_brief import (
    ActivityType,
    ConflictCategory,
    ConflictEntry,
    ConflictSeverity,
    ConflictSource,
    ConflictStatus,
    FHIRCode,
    PlanActivity,
    PlanGoal,
    PlanningBrief,
    TargetValue,
)
from acp_writer.services.artifact_resolver import plan_conflict_from_entry
from acp_writer.services.bff import _extract_view_from_bundle
from acp_writer.validators.fhir_bundle_builder import build_fhir_bundle


def _brief_with_conflict() -> PlanningBrief:
    return PlanningBrief(
        patient_reference="Patient/p1",
        applicable_cpgs=["SYN-HTN-2026-001", "SYN-DM2-2026-001"],
        goals=[
            PlanGoal(
                description="Lower BP <140/90",
                target_measure_code=FHIRCode(system="http://loinc.org", code="8480-6", display="Systolic BP"),
                target_value=TargetValue(high=140, unit="mmHg"),
                source_cpg="SYN-HTN-2026-001",
            ),
            PlanGoal(
                description="Lower BP <130/80",
                target_measure_code=FHIRCode(system="http://loinc.org", code="8480-6", display="Systolic BP"),
                target_value=TargetValue(high=130, unit="mmHg"),
                source_cpg="SYN-DM2-2026-001",
            ),
        ],
        activities=[
            PlanActivity(
                type=ActivityType.MEDICATION,
                description="Lisinopril",
                dose="10 mg",
                source_recommendation_id="rec-123",
                source_cpg="SYN-HTN-2026-001",
            ),
        ],
        conflicts=[
            ConflictEntry(
                id="conf-abc12345",
                category=ConflictCategory.DIVERGENT_TARGET,
                severity=ConflictSeverity.WARNING,
                status=ConflictStatus.DETECTED,
                description="Two guidelines set different BP targets",
                rationale="HTN targets <140/90; DM2 targets <130/80",
                suggested_resolution="Prefer the diabetes guideline's <130/80 target and note the divergence",
                confidence="high",
                goal_indices=[0, 1],
                activity_indices=[0],
                sources=[
                    ConflictSource(cpg_id="SYN-HTN-2026-001", recommendation_id="rec-123", excerpt="<140/90"),
                    ConflictSource(cpg_id="SYN-DM2-2026-001", recommendation_id="dm2-rec-002", excerpt="<130/80"),
                ],
            )
        ],
    )


class TestBundleReadBack:
    def test_conflict_reconstructed_from_provenance(self):
        bundle = build_fhir_bundle(_brief_with_conflict())
        _goals, _acts, conflicts = _extract_view_from_bundle(bundle)
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c["id"] == "conf-abc12345"
        assert c["severity"] == "warning"
        assert c["category"] == "divergent_target"
        assert c["status"] == "detected"
        assert c["confidence"] == "high"
        assert "different BP targets" in c["description"]
        # F16b: the analyst's suggested resolution survives the bundle round-trip
        # via the conflict-suggested-resolution Provenance extension.
        assert c["suggestedResolution"] == (
            "Prefer the diabetes guideline's <130/80 target and note the divergence"
        )

    def test_sources_reconstructed(self):
        bundle = build_fhir_bundle(_brief_with_conflict())
        _g, _a, conflicts = _extract_view_from_bundle(bundle)
        srcs = {s["cpgId"]: s for s in conflicts[0]["sources"]}
        assert set(srcs) == {"SYN-HTN-2026-001", "SYN-DM2-2026-001"}
        assert srcs["SYN-HTN-2026-001"]["recommendationId"] == "rec-123"
        assert srcs["SYN-HTN-2026-001"]["excerpt"] == "<140/90"

    def test_no_conflicts_yields_empty(self):
        brief = _brief_with_conflict()
        brief.conflicts = []
        bundle = build_fhir_bundle(brief)
        _g, _a, conflicts = _extract_view_from_bundle(bundle)
        assert conflicts == []

    def test_non_conflict_provenance_is_ignored(self):
        # C6: after dropping the redundant is_conflict_provenance() pre-check,
        # a plain AI-Provenance (no conflict-id extension) must still be filtered
        # out — plan_conflict_from_provenance returns None for it.
        brief = _brief_with_conflict()
        brief.conflicts = []
        bundle = build_fhir_bundle(brief)
        bundle["entry"].append({
            "resource": {
                "resourceType": "Provenance",
                "target": [{"reference": "CarePlan/x"}],
                "extension": [{"url": "https://example.org/some-other-ext", "valueString": "y"}],
            }
        })
        _g, _a, conflicts = _extract_view_from_bundle(bundle)
        assert conflicts == []

    def test_resolution_round_trips_via_provenance(self):
        # F17c: a resolved conflict's clinician resolution note survives the
        # bundle round-trip via the conflict-resolution Provenance extension.
        brief = _brief_with_conflict()
        brief.conflicts[0].status = ConflictStatus.RESOLVED
        brief.conflicts[0].resolution = (
            "Resolve as suggested — kept the diabetes <130/80 target, dropped <140/90"
        )
        bundle = build_fhir_bundle(brief)
        _g, _a, conflicts = _extract_view_from_bundle(bundle)
        assert conflicts[0]["status"] == "resolved"
        assert conflicts[0]["resolution"] == (
            "Resolve as suggested — kept the diabetes <130/80 target, dropped <140/90"
        )

    def test_medium_confidence_round_trips_back_to_medium(self):
        # F8: the analyst's "medium" is stored on the AIconfidence extension as
        # the certainty-rating code "moderate" (no "medium" code exists there).
        # Read-back must invert that mapping so the UI sees "medium" again,
        # not the persisted "moderate".
        brief = _brief_with_conflict()
        brief.conflicts[0].confidence = "medium"
        bundle = build_fhir_bundle(brief)
        _g, _a, conflicts = _extract_view_from_bundle(bundle)
        assert conflicts[0]["confidence"] == "medium"

    def test_source_with_display_delimiters_round_trips_exactly(self):
        # F9: a cpg id / excerpt that itself contains the display-string
        # delimiters (" · rec ", " — ") must survive the round-trip intact.
        # The old display-string parse corrupted these; structural source
        # extensions carry the exact values.
        brief = _brief_with_conflict()
        brief.conflicts[0].sources = [
            ConflictSource(
                cpg_id="CPG · rec tricky",
                recommendation_id="rec-9",
                excerpt="goal — target <140/90 · rec note",
            )
        ]
        bundle = build_fhir_bundle(brief)
        _g, _a, conflicts = _extract_view_from_bundle(bundle)
        src = conflicts[0]["sources"][0]
        assert src["cpgId"] == "CPG · rec tricky"
        assert src["recommendationId"] == "rec-9"
        assert src["excerpt"] == "goal — target <140/90 · rec note"


class TestEntryMapping:
    def test_maps_snake_to_camel(self):
        entry = _brief_with_conflict().conflicts[0].model_dump(mode="json")
        pc = plan_conflict_from_entry(entry)
        assert pc["id"] == "conf-abc12345"
        assert pc["severity"] == "warning"
        assert pc["category"] == "divergent_target"
        assert pc["status"] == "detected"
        assert pc["confidence"] == "high"
        assert pc["sources"][0]["cpgId"] == "SYN-HTN-2026-001"
        assert pc["sources"][0]["recommendationId"] == "rec-123"
        assert pc["sources"][0]["excerpt"] == "<140/90"
        # F16b: the live (brief-entry) read path maps suggested_resolution too.
        assert pc["suggestedResolution"] == (
            "Prefer the diabetes guideline's <130/80 target and note the divergence"
        )

    def test_maps_resolution(self):
        # F17c: the live read path maps the clinician resolution note too.
        pc = plan_conflict_from_entry({
            "id": "c1", "description": "d", "status": "resolved",
            "resolution": "merged the two diet activities",
        })
        assert pc["status"] == "resolved"
        assert pc["resolution"] == "merged the two diet activities"

    def test_minimal_entry(self):
        pc = plan_conflict_from_entry({"id": "c1", "description": "d"})
        assert pc == {"id": "c1", "description": "d"}

    def test_source_without_rec_or_excerpt(self):
        entry = {"id": "c1", "description": "d", "sources": [{"cpg_id": "X"}]}
        pc = plan_conflict_from_entry(entry)
        assert pc["sources"] == [{"cpgId": "X"}]
