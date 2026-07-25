"""FHIR Bundle Builder — deterministic FHIR R4 resource construction.

Produces CarePlan, Goal, MedicationRequest, ServiceRequest,
AI-Device, AI-Provenance resources from a PlanningBrief.
All resources get AIAST meta.security tags.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from acp_writer.planning_brief import ActivityType, PlanningBrief

AIAST_SECURITY = {
    "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
    "code": "AIAST",
    "display": "asserted by AI system",
}

AI_TRANSPARENCY_PROFILE = "http://hl7.org/fhir/uv/ai-transparency/StructureDefinition"


def _uuid() -> str:
    return str(uuid.uuid4())


def _urn(uid: str) -> str:
    return f"urn:uuid:{uid}"


def _meta() -> dict:
    return {"security": [AIAST_SECURITY]}


def _entry(resource: dict, uid: str) -> dict:
    return {
        "fullUrl": _urn(uid),
        "resource": resource,
        "request": {
            "method": "POST",
            "url": resource["resourceType"],
        },
    }


def _codeable_concept(code_dict: dict | None, text: str | None = None) -> dict:
    if code_dict:
        cc: dict[str, Any] = {
            "coding": [{
                "system": code_dict.get("system", ""),
                "code": code_dict.get("code", ""),
            }],
        }
        if code_dict.get("display"):
            cc["coding"][0]["display"] = code_dict["display"]
        if text:
            cc["text"] = text
        elif code_dict.get("display"):
            cc["text"] = code_dict["display"]
        return cc
    if text:
        return {"text": text}
    return {"text": "Unknown"}


def build_fhir_bundle(
    brief: PlanningBrief,
    patient_demographics: dict[str, Any] | None = None,
) -> dict:
    """Build a complete FHIR R4 transaction Bundle from a PlanningBrief."""
    entries: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    bundle_id = _uuid()

    patient_uid = _uuid()
    patient_urn = _urn(patient_uid)
    patient_resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": patient_uid,
        "meta": _meta(),
    }
    if_none_exist = None
    if patient_demographics:
        identifiers = patient_demographics.get("identifiers", [])
        if identifiers:
            patient_resource["identifier"] = [
                {"system": ident["system"], "value": ident["value"]}
                for ident in identifiers
            ]
            first = identifiers[0]
            if_none_exist = f"identifier={first['system']}|{first['value']}"
        if patient_demographics.get("name"):
            patient_resource["name"] = [{"text": patient_demographics["name"]}]
        if patient_demographics.get("gender"):
            patient_resource["gender"] = patient_demographics["gender"]
        if patient_demographics.get("birth_date"):
            patient_resource["birthDate"] = patient_demographics["birth_date"]

    patient_entry: dict[str, Any] = {
        "fullUrl": patient_urn,
        "resource": patient_resource,
        "request": {
            "method": "POST",
            "url": "Patient",
        },
    }
    if if_none_exist:
        patient_entry["request"]["ifNoneExist"] = if_none_exist
    entries.append(patient_entry)

    patient_ref = patient_urn

    goal_uids: list[str] = []
    activity_refs: list[dict] = []
    activity_uid_map: dict[int, str] = {}

    for goal in brief.goals:
        uid = _uuid()
        goal_uids.append(uid)
        goal_resource: dict[str, Any] = {
            "resourceType": "Goal",
            "id": uid,
            "meta": _meta(),
            "lifecycleStatus": "proposed",
            "description": {"text": goal.description},
            "subject": {"reference": patient_ref},
        }
        if goal.target_measure_code and goal.target_value:
            target: dict[str, Any] = {
                "measure": _codeable_concept(
                    goal.target_measure_code.model_dump() if goal.target_measure_code else None,
                ),
            }
            detail: dict[str, Any] = {}
            if goal.target_value.high is not None:
                detail["high"] = {
                    "value": goal.target_value.high,
                    "unit": goal.target_value.unit,
                    "system": "http://unitsofmeasure.org",
                }
            if goal.target_value.low is not None:
                detail["low"] = {
                    "value": goal.target_value.low,
                    "unit": goal.target_value.unit,
                    "system": "http://unitsofmeasure.org",
                }
            if detail:
                target["detailRange"] = detail
            goal_resource["target"] = [target]
        entries.append(_entry(goal_resource, uid))

    for i, activity in enumerate(brief.activities):
        uid = _uuid()

        if activity.type == ActivityType.MEDICATION:
            activity_uid_map[i] = uid
            resource: dict[str, Any] = {
                "resourceType": "MedicationRequest",
                "id": uid,
                "meta": _meta(),
                "status": "draft",
                "intent": "proposal",
                "subject": {"reference": patient_ref},
                "medicationCodeableConcept": _codeable_concept(
                    activity.code.model_dump() if activity.code else None,
                    activity.description,
                ),
            }
            if activity.dose:
                resource["dosageInstruction"] = [{
                    "text": f"{activity.dose} {activity.route or ''} {activity.frequency or ''}".strip(),
                }]
            entries.append(_entry(resource, uid))
            activity_refs.append({"reference": {"reference": _urn(uid)}})

        elif activity.type in (ActivityType.MONITORING, ActivityType.REFERRAL):
            activity_uid_map[i] = uid
            resource = {
                "resourceType": "ServiceRequest",
                "id": uid,
                "meta": _meta(),
                "status": "draft",
                "intent": "proposal",
                "subject": {"reference": patient_ref},
                "code": _codeable_concept(
                    activity.code.model_dump() if activity.code else None,
                    activity.description,
                ),
            }
            if activity.frequency:
                resource["note"] = [{"text": f"Frequency: {activity.frequency}"}]
            entries.append(_entry(resource, uid))
            activity_refs.append({"reference": {"reference": _urn(uid)}})

        else:
            activity_refs.append({
                "performedActivity": [_codeable_concept(
                    activity.code.model_dump() if activity.code else None,
                    activity.description,
                )],
            })

    careplan_uid = _uuid()
    careplan: dict[str, Any] = {
        "resourceType": "CarePlan",
        "id": careplan_uid,
        "meta": _meta(),
        "status": "draft",
        "intent": "proposal",
        "title": "Care Plan",
        "category": [{
            "coding": [{
                "system": "http://hl7.org/fhir/us/core/CodeSystem/careplan-category",
                "code": "assess-plan",
            }],
        }],
        "subject": {"reference": patient_ref},
        "created": now,
        "goal": [{"reference": _urn(uid)} for uid in goal_uids],
        "activity": activity_refs,
    }
    entries.append(_entry(careplan, careplan_uid))

    device_uid = _uuid()
    ai_device: dict[str, Any] = {
        "resourceType": "Device",
        "id": device_uid,
        "meta": {
            "profile": [f"{AI_TRANSPARENCY_PROFILE}/AI-Device"],
            "security": [AIAST_SECURITY],
        },
        "type": {
            "coding": [{
                "system": "http://hl7.org/fhir/uv/ai-transparency/CodeSystem/ai-device-type",
                "code": "Artificial-Intelligence",
                "display": "Artificial Intelligence",
            }],
        },
        "deviceName": [{"name": "acp-writer", "type": "user-friendly-name"}],
        "version": [{"value": "0.2.0"}],
    }
    entries.append(_entry(ai_device, device_uid))

    prov_uid = _uuid()
    all_target_refs = [{"reference": _urn(careplan_uid)}]
    all_target_refs.extend({"reference": _urn(uid)} for uid in goal_uids)
    for idx, uid in activity_uid_map.items():
        all_target_refs.append({"reference": _urn(uid)})

    prov_entities: list[dict] = []
    for cpg_id in brief.applicable_cpgs:
        prov_entities.append({
            "role": "derivation",
            "what": {"display": f"CPG: {cpg_id}"},
        })

    ai_provenance: dict[str, Any] = {
        "resourceType": "Provenance",
        "id": prov_uid,
        "meta": {
            "profile": [f"{AI_TRANSPARENCY_PROFILE}/AI-Provenance"],
            "security": [AIAST_SECURITY],
        },
        "target": all_target_refs,
        "recorded": now,
        "reason": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
                "code": "AIAST",
            }],
        }],
        "agent": [{
            "type": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                    "code": "author",
                }],
            },
            "who": {"reference": _urn(device_uid)},
        }],
        "entity": prov_entities,
    }
    entries.append(_entry(ai_provenance, prov_uid))

    for i, activity in enumerate(brief.activities):
        if not activity.source_recommendation_id:
            continue
        uid = activity_uid_map.get(i)
        if uid:
            prov_target: dict[str, Any] = {"reference": _urn(uid)}
        else:
            prov_target = {
                "reference": _urn(careplan_uid),
                "extension": [{
                    "url": f"{AI_TRANSPARENCY_PROFILE}/targetPath",
                    "valueString": f"CarePlan.activity[{i}].performedActivity",
                }],
            }

        act_prov_uid = _uuid()
        act_provenance: dict[str, Any] = {
            "resourceType": "Provenance",
            "id": act_prov_uid,
            "meta": _meta(),
            "target": [prov_target],
            "recorded": now,
            "agent": [{
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                        "code": "author",
                    }],
                },
                "who": {"reference": _urn(device_uid)},
            }],
            "entity": [{
                "role": "source",
                "what": {
                    "display": f"Recommendation: {activity.source_recommendation_id}",
                    "identifier": {
                        "value": activity.source_recommendation_id,
                    },
                },
            }],
        }
        entries.append(_entry(act_provenance, act_prov_uid))

    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "id": bundle_id,
        "type": "transaction",
        "timestamp": now,
        "entry": entries,
    }
    return bundle
