"""Temporal index for IPS bundles.

Indexes observations, medications, and procedures by code and date
for efficient temporal queries. Built once per bundle, reused across
queries.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from acp_writer.tools.ips_extractor import (
    _extract_obs_value,
    _get_effective_date,
    _get_resources,
    _has_code,
)

logger = logging.getLogger(__name__)


@dataclass
class IndexedObservation:
    """A single observation value with its temporal and provenance metadata."""
    effective_dt: datetime | None
    value: Any
    unit: str | None
    fhir_reference: str
    has_date: bool = True


@dataclass
class IndexedMedication:
    """A medication with its start date for cross-resource temporal queries."""
    start_date: datetime | None
    fhir_reference: str
    resource_type: str


@dataclass
class TemporalIndex:
    """In-memory index of IPS bundle observations, medications, and procedures by code.

    Observations are keyed by "system|code" and sorted descending by date.
    """
    observations: dict[str, list[IndexedObservation]] = field(default_factory=dict)
    medications: dict[str, list[IndexedMedication]] = field(default_factory=dict)
    procedures: dict[str, list[dict]] = field(default_factory=dict)
    undated_count: int = 0

    def get_observations(self, code_token: str) -> list[IndexedObservation]:
        return self.observations.get(code_token, [])


def _parse_datetime(date_str: str | None) -> datetime | None:
    """Parse a FHIR date/datetime string to a timezone-aware datetime."""
    if not date_str:
        return None
    from datetime import timezone as tz
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz.utc)
        return dt
    except (ValueError, TypeError):
        try:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            return dt.replace(tzinfo=tz.utc)
        except (ValueError, TypeError):
            return None


def build_temporal_index(bundle: dict) -> TemporalIndex:
    """Build an in-memory temporal index from a FHIR IPS bundle."""
    index = TemporalIndex()

    for obs in _get_resources(bundle, "Observation"):
        obs_id = obs.get("id", "unknown")
        ref = f"Observation/{obs_id}"
        effective_str = _get_effective_date(obs)
        effective_dt = _parse_datetime(effective_str)

        top_codings = obs.get("code", {}).get("coding", [])
        for coding in top_codings:
            system = coding.get("system", "")
            code = coding.get("code", "")
            if not system or not code:
                continue
            code_token = f"{system}|{code}"

            value, unit = _extract_obs_value(obs)
            entry = IndexedObservation(
                effective_dt=effective_dt,
                value=value,
                unit=unit,
                fhir_reference=ref,
                has_date=effective_dt is not None,
            )
            index.observations.setdefault(code_token, []).append(entry)
            if not effective_dt:
                index.undated_count += 1

        for component in obs.get("component", []):
            comp_codings = component.get("code", {}).get("coding", [])
            for coding in comp_codings:
                system = coding.get("system", "")
                code = coding.get("code", "")
                if not system or not code:
                    continue
                code_token = f"{system}|{code}"

                value, unit = _extract_obs_value(component)
                if value is not None:
                    entry = IndexedObservation(
                        effective_dt=effective_dt,
                        value=value,
                        unit=unit,
                        fhir_reference=ref,
                        has_date=effective_dt is not None,
                    )
                    index.observations.setdefault(code_token, []).append(entry)

    for resource_type in ["MedicationStatement", "MedicationRequest"]:
        for med in _get_resources(bundle, resource_type):
            status = med.get("status", "")
            if status in ("cancelled", "entered-in-error", "stopped"):
                continue

            med_id = med.get("id", "unknown")
            ref = f"{resource_type}/{med_id}"

            start_str = (
                med.get("authoredOn")
                or med.get("effectiveDateTime")
                or (med.get("effectivePeriod", {}) or {}).get("start")
            )
            start_dt = _parse_datetime(start_str)

            for coding in med.get("medicationCodeableConcept", {}).get("coding", []):
                system = coding.get("system", "")
                code = coding.get("code", "")
                if not system or not code:
                    continue
                code_token = f"{system}|{code}"
                index.medications.setdefault(code_token, []).append(
                    IndexedMedication(
                        start_date=start_dt,
                        fhir_reference=ref,
                        resource_type=resource_type,
                    )
                )

    from datetime import timezone as tz
    _MIN_DT = datetime.min.replace(tzinfo=tz.utc)

    for code_token, obs_list in index.observations.items():
        obs_list.sort(
            key=lambda o: o.effective_dt or _MIN_DT,
            reverse=True,
        )

    return index
