"""Tests for temporal index and query primitives."""

import json
from datetime import date
from pathlib import Path

from acp_writer.tools.temporal_index import build_temporal_index
from acp_writer.tools.temporal_queries import (
    consecutive_above,
    cross_resource_temporal,
    observation_count,
    observations_in_window,
    rate_of_change,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent
BUNDLES_DIR = PROJECT_ROOT / "acp-writer" / "benchmarks" / "bundles"

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SBP_CODE = f"{LOINC}|8480-6"
DBP_CODE = f"{LOINC}|8462-4"
BP_PANEL = f"{LOINC}|85354-9"
EGFR_CODE = f"{LOINC}|33914-3"
BMP_CODE = f"{LOINC}|51990-0"
LISINOPRIL_CODE = f"{RXNORM}|314076"

REF_DATE = date(2026, 6, 1)


def _load(name: str) -> dict:
    return json.loads((BUNDLES_DIR / name).read_text())


class TestTemporalIndex:
    def test_indexes_bp_components(self):
        bundle = _load("htn-temporal-01.json")
        index = build_temporal_index(bundle)
        sbp_obs = index.get_observations(SBP_CODE)
        assert len(sbp_obs) == 8
        assert sbp_obs[0].value == 144  # most recent first

    def test_indexes_egfr(self):
        bundle = _load("ckd-declining-01.json")
        index = build_temporal_index(bundle)
        egfr_obs = index.get_observations(EGFR_CODE)
        assert len(egfr_obs) == 7
        assert egfr_obs[0].value == 40  # most recent

    def test_indexes_medications(self):
        bundle = _load("ckd-declining-01.json")
        index = build_temporal_index(bundle)
        lisinopril = index.medications.get(LISINOPRIL_CODE, [])
        assert len(lisinopril) == 1
        assert lisinopril[0].start_date is not None

    def test_handles_missing_dates(self):
        bundle = _load("edge-missing-dates.json")
        index = build_temporal_index(bundle)
        assert index.undated_count > 0

    def test_sorted_descending(self):
        bundle = _load("htn-temporal-01.json")
        index = build_temporal_index(bundle)
        sbp_obs = index.get_observations(SBP_CODE)
        dates = [o.effective_dt for o in sbp_obs if o.effective_dt]
        assert dates == sorted(dates, reverse=True)


class TestObservationsInWindow:
    def test_3_month_window(self):
        bundle = _load("htn-temporal-01.json")
        index = build_temporal_index(bundle)
        result = observations_in_window(index, SBP_CODE, "P3M", REF_DATE)
        assert result.found
        assert len(result.value) == 5  # Mar-May readings

    def test_6_month_window(self):
        bundle = _load("htn-temporal-01.json")
        index = build_temporal_index(bundle)
        result = observations_in_window(index, SBP_CODE, "P6M", REF_DATE)
        assert result.found
        assert len(result.value) == 8

    def test_missing_code(self):
        bundle = _load("htn-temporal-01.json")
        index = build_temporal_index(bundle)
        result = observations_in_window(index, f"{LOINC}|99999-9", "P3M", REF_DATE)
        assert not result.found
        assert result.insufficient_data


class TestObservationCount:
    def test_count_above_threshold(self):
        bundle = _load("htn-temporal-01.json")
        index = build_temporal_index(bundle)
        result = observation_count(index, SBP_CODE, "P3M", REF_DATE, threshold=140, comparator="ge")
        assert result.value == 5

    def test_count_all_in_year(self):
        bundle = _load("ckd-declining-01.json")
        index = build_temporal_index(bundle)
        result = observation_count(index, EGFR_CODE, "P1Y", REF_DATE)
        assert result.value == 5


class TestConsecutiveAbove:
    def test_consecutive_stops_at_below(self):
        bundle = _load("htn-temporal-01.json")
        index = build_temporal_index(bundle)
        result = consecutive_above(index, SBP_CODE, 140, REF_DATE)
        assert result.value == 5
        assert len(result.provenance) == 5

    def test_all_below(self):
        bundle = _load("htn-temporal-01.json")
        index = build_temporal_index(bundle)
        result = consecutive_above(index, SBP_CODE, 200, REF_DATE)
        assert result.value == 0


class TestRateOfChange:
    def test_declining_egfr(self):
        bundle = _load("ckd-declining-01.json")
        index = build_temporal_index(bundle)
        result = rate_of_change(index, EGFR_CODE, "P1Y", REF_DATE)
        assert result.found
        assert result.value < 0  # declining
        assert -12 < result.value < -5  # roughly -8 per year

    def test_insufficient_single_reading(self):
        bundle = _load("htn-temporal-01.json")
        index = build_temporal_index(bundle)
        result = rate_of_change(index, SBP_CODE, "P7D", REF_DATE)
        # Only 1 reading in last 7 days (May 30)
        assert not result.found
        assert result.insufficient_data


class TestCrossResourceTemporal:
    def test_bmp_within_2_weeks_of_lisinopril(self):
        bundle = _load("complex-patient-01.json")
        index = build_temporal_index(bundle)
        result = cross_resource_temporal(
            index, bundle, LISINOPRIL_CODE, BMP_CODE, "P14D"
        )
        assert result.found
        assert result.value is True

    def test_no_matching_medication(self):
        bundle = _load("htn-temporal-01.json")
        index = build_temporal_index(bundle)
        result = cross_resource_temporal(
            index, bundle, LISINOPRIL_CODE, BMP_CODE, "P14D"
        )
        assert not result.found
        assert result.insufficient_data
