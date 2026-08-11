"""Condensed IPS serializer — flatten a FHIR IPS bundle into compact clinical text.

Used as LLM context for query-plan synthesis and agent-based QA.
Never the source of final numeric answers — those come from the
extraction functions.

Based on FHIRBench findings: condensed format achieves 95% of raw
JSON clinical quality at 83% fewer tokens.
"""

from datetime import datetime

from acp_writer.tools.ips_extractor import _get_effective_date, _get_resources


def serialize_ips(bundle: dict) -> str:
    """Convert a FHIR IPS bundle into a condensed clinical narrative."""
    sections = []

    patient_section = _serialize_patient(bundle)
    if patient_section:
        sections.append(patient_section)

    conditions = _serialize_conditions(bundle)
    if conditions:
        sections.append(conditions)

    medications = _serialize_medications(bundle)
    if medications:
        sections.append(medications)

    allergies = _serialize_allergies(bundle)
    if allergies:
        sections.append(allergies)

    observations = _serialize_observations(bundle)
    if observations:
        sections.append(observations)

    procedures = _serialize_procedures(bundle)
    if procedures:
        sections.append(procedures)

    return "\n\n".join(sections)


def _serialize_patient(bundle: dict) -> str | None:
    patients = _get_resources(bundle, "Patient")
    if not patients:
        return None

    p = patients[0]
    parts = ["PATIENT:"]

    names = p.get("name", [])
    if names:
        name = names[0]
        given = " ".join(name.get("given", []))
        family = name.get("family", "")
        parts.append(f"  Name: {given} {family}".strip())

    if p.get("gender"):
        parts.append(f"  Gender: {p['gender']}")

    if p.get("birthDate"):
        parts.append(f"  DOB: {p['birthDate']}")

    return "\n".join(parts)


def _serialize_conditions(bundle: dict) -> str | None:
    conditions = _get_resources(bundle, "Condition")
    if not conditions:
        return None

    lines = ["CONDITIONS:"]
    for c in conditions:
        display = _get_display(c.get("code", {}))
        status_coding = c.get("clinicalStatus", {}).get("coding", [])
        status = status_coding[0].get("code", "unknown") if status_coding else "unknown"
        onset = c.get("onsetDateTime", "")
        line = f"  - {display} [{status}]"
        if onset:
            line += f" (onset: {onset[:10]})"
        lines.append(line)

    return "\n".join(lines)


def _serialize_medications(bundle: dict) -> str | None:
    meds = []
    for rt in ["MedicationStatement", "MedicationRequest"]:
        for m in _get_resources(bundle, rt):
            status = m.get("status", "unknown")
            if status in ("cancelled", "entered-in-error", "stopped"):
                continue
            display = _get_display(m.get("medicationCodeableConcept", {}))
            authored = m.get("authoredOn", "")
            line = f"  - {display} [{status}]"
            if authored:
                line += f" (started: {authored[:10]})"
            meds.append(line)

    if not meds:
        return None

    return "MEDICATIONS:\n" + "\n".join(meds)


def _serialize_allergies(bundle: dict) -> str | None:
    allergies = _get_resources(bundle, "AllergyIntolerance")
    if not allergies:
        return None

    lines = ["ALLERGIES:"]
    for a in allergies:
        display = _get_display(a.get("code", {}))
        criticality = a.get("criticality", "")
        status_coding = a.get("clinicalStatus", {}).get("coding", [])
        status = status_coding[0].get("code", "unknown") if status_coding else "unknown"
        line = f"  - {display} [{status}]"
        if criticality:
            line += f" (criticality: {criticality})"
        lines.append(line)

    return "\n".join(lines)


def _serialize_observations(bundle: dict) -> str | None:
    observations = _get_resources(bundle, "Observation")
    if not observations:
        return None

    grouped: dict[str, list[tuple[str, str]]] = {}

    for obs in observations:
        display = _get_display(obs.get("code", {}))
        date_str = _get_effective_date(obs)
        date_short = date_str[:10] if date_str else "no date"

        components = obs.get("component", [])
        if components:
            values = []
            for comp in components:
                comp_display = _get_display(comp.get("code", {}))
                comp_val = _format_value(comp)
                if comp_val:
                    values.append(f"{comp_display}: {comp_val}")
            if values:
                val_str = "; ".join(values)
                grouped.setdefault(display, []).append((date_short, val_str))
        else:
            val_str = _format_value(obs)
            if val_str:
                grouped.setdefault(display, []).append((date_short, val_str))
            else:
                grouped.setdefault(display, []).append((date_short, "(no value)"))

    lines = ["OBSERVATIONS:"]
    for obs_name, readings in grouped.items():
        readings.sort(key=lambda r: r[0], reverse=True)
        if len(readings) == 1:
            date_short, val = readings[0]
            lines.append(f"  - {obs_name}: {val} ({date_short})")
        else:
            lines.append(f"  - {obs_name}:")
            for date_short, val in readings:
                lines.append(f"      {date_short}: {val}")

    return "\n".join(lines)


def _serialize_procedures(bundle: dict) -> str | None:
    procedures = _get_resources(bundle, "Procedure")
    if not procedures:
        return None

    lines = ["PROCEDURES:"]
    for p in procedures:
        display = _get_display(p.get("code", {}))
        status = p.get("status", "unknown")
        date_str = p.get("performedDateTime", "")
        line = f"  - {display} [{status}]"
        if date_str:
            line += f" ({date_str[:10]})"
        lines.append(line)

    return "\n".join(lines)


def _get_display(codeable_concept: dict) -> str:
    """Get the best display text from a CodeableConcept."""
    codings = codeable_concept.get("coding", [])
    for coding in codings:
        if coding.get("display"):
            return coding["display"]
    if codeable_concept.get("text"):
        return codeable_concept["text"]
    for coding in codings:
        if coding.get("code"):
            return f"{coding.get('system', '')}|{coding['code']}"
    return "unknown"


def _format_value(obs_or_component: dict) -> str | None:
    """Format an observation value for the condensed representation."""
    vq = obs_or_component.get("valueQuantity")
    if vq and vq.get("value") is not None:
        unit = vq.get("unit", "")
        return f"{vq['value']} {unit}".strip()

    vcc = obs_or_component.get("valueCodeableConcept")
    if vcc:
        return _get_display(vcc)

    vs = obs_or_component.get("valueString")
    if vs is not None:
        return vs

    vb = obs_or_component.get("valueBoolean")
    if vb is not None:
        return str(vb)

    return None
