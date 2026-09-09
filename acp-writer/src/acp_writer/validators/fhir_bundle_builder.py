"""FHIR Bundle Builder — deterministic FHIR R4 resource construction.

Produces Patient, CarePlan, Goal, MedicationRequest, ServiceRequest, and the
AI-transparency resources (AI-Device, AI-Provenance, AI-InputPrompt /
AI-ModelCard DocumentReferences) from a PlanningBrief. All AI-produced
resources carry AIAST ``meta.security`` tags.

AI-transparency resource construction lives in
``acp_writer.services.ai_transparency`` (the HL7 AI Transparency IG is the
source of truth); this builder wires those resources into the bundle.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from acp_writer.planning_brief import ActivityType, PlanningBrief
from acp_writer.services import ai_transparency as ait
from acp_writer.services.ai_transparency import ACP_EXT_BASE, aiast_security

# Retained for import back-compat; sourced from the IG-conformant helper.
AIAST_SECURITY = aiast_security()


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
    model_id: str | None = None,
    prompts: dict[str, str] | None = None,
) -> dict:
    """Build a complete FHIR R4 transaction Bundle from a PlanningBrief.

    ``model_id`` names the LLM behind the AI-Device (from state ``llm_model``).
    ``prompts`` maps a human label → rendered prompt text; each becomes an
    AI-InputPrompt DocumentReference (when ``ACP_CAPTURE_PROMPTS`` is enabled).
    """
    entries: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    prompts = prompts or {}

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
            detail_entry: dict[str, Any] = {
                "detail": {
                    "status": "not-started",
                    "description": activity.description,
                },
            }
            code = _codeable_concept(
                activity.code.model_dump() if activity.code else None,
                activity.description,
            )
            if code:
                detail_entry["detail"]["code"] = code
            activity_refs.append(detail_entry)

    careplan_uid = _uuid()
    careplan_urn = _urn(careplan_uid)
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
    # WS4 marker: exactly one boolean extension when the plan has conflicts.
    if brief.conflicts:
        careplan["extension"] = [{
            "url": f"{ACP_EXT_BASE}/careplan-conflict-detected",
            "valueBoolean": True,
        }]
    entries.append(_entry(careplan, careplan_uid))

    # ── AI-Device ───────────────────────────────────────────────────────────
    device_uid = _uuid()
    device_urn = _urn(device_uid)
    ai_device = ait.build_ai_device(device_uid, model_id)
    entries.append(_entry(ai_device, device_uid))

    # ── AI-InputPrompt DocumentReferences (captured prompts) ─────────────────
    input_prompt_urns: list[str] = []
    if ait.prompts_capture_enabled():
        for label, text in prompts.items():
            if not text:
                continue
            docref_uid = _uuid()
            docref = ait.build_input_prompt_docref(
                docref_uid, text, f"Rendered prompt: {label}"
            )
            entries.append(_entry(docref, docref_uid))
            input_prompt_urns.append(_urn(docref_uid))

    # ── AI-ModelCard DocumentReference (optional, env-gated) ─────────────────
    model_card_urn: str | None = None
    mc_url = ait.model_card_url()
    if mc_url:
        mc_uid = _uuid()
        entries.append(_entry(ait.build_model_card_docref(mc_uid, mc_url), mc_uid))
        model_card_urn = _urn(mc_uid)

    # ── Bundle-level AI-Provenance ───────────────────────────────────────────
    all_targets = [{"reference": careplan_urn}]
    all_targets.extend({"reference": _urn(uid)} for uid in goal_uids)
    for _idx, uid in activity_uid_map.items():
        all_targets.append({"reference": _urn(uid)})

    prov_entities: list[dict] = []
    for cpg_id in brief.applicable_cpgs:
        prov_entities.append({
            "role": "derivation",
            "what": {"display": f"CPG: {cpg_id}"},
        })
    for ip_urn in input_prompt_urns:
        prov_entities.append({"role": "derivation", "what": {"reference": ip_urn}})
    if model_card_urn:
        prov_entities.append({"role": "derivation", "what": {"reference": model_card_urn}})

    prov_uid = _uuid()
    ai_provenance = ait.build_ai_provenance(
        prov_uid=prov_uid,
        targets=all_targets,
        device_urn=device_urn,
        recorded=now,
        occurred=now,
        entities=prov_entities or None,
    )
    entries.append(_entry(ai_provenance, prov_uid))

    # ── Per-activity source Provenances ──────────────────────────────────────
    for i, activity in enumerate(brief.activities):
        if not activity.source_recommendation_id:
            continue
        uid = activity_uid_map.get(i)
        if uid:
            prov_target: dict[str, Any] = {"reference": _urn(uid)}
        else:
            prov_target = {
                "reference": careplan_urn,
                "extension": [ait.targetPath_ext(f"CarePlan.activity[{i}].detail")],
            }

        act_prov_uid = _uuid()
        act_provenance = ait.build_ai_provenance(
            prov_uid=act_prov_uid,
            targets=[prov_target],
            device_urn=device_urn,
            recorded=now,
            occurred=now,
            entities=[{
                "role": "source",
                "what": {
                    "display": f"Recommendation: {activity.source_recommendation_id}",
                    "identifier": {"value": activity.source_recommendation_id},
                },
            }],
        )
        entries.append(_entry(act_provenance, act_prov_uid))

    # ── Conflict Provenances (WS4) ───────────────────────────────────────────
    goal_urns = [_urn(uid) for uid in goal_uids]
    activity_urn_map = {idx: _urn(uid) for idx, uid in activity_uid_map.items()}
    for conflict in brief.conflicts:
        conf_prov_uid = _uuid()
        conf_prov = ait.build_conflict_provenance(
            prov_uid=conf_prov_uid,
            conflict=conflict,
            careplan_urn=careplan_urn,
            goal_urns=goal_urns,
            activity_urn_map=activity_urn_map,
            device_urn=device_urn,
            recorded=now,
            occurred=now,
        )
        entries.append(_entry(conf_prov, conf_prov_uid))

    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "id": bundle_id,
        "type": "transaction",
        "timestamp": now,
        "entry": entries,
    }
    return bundle
