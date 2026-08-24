"""BFF (Backend-for-Frontend) service for the acp-writer React UI.

Mediates between the SPA and SonataFlow/MinIO/backend pods.
Each backend dependency is independently optional — the BFF
degrades gracefully when SonataFlow or MinIO is not configured.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import mlflow
import requests as http_requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from cpg_contracts.artifact_store import ArtifactStore

from acp_writer.services.artifact_resolver import enrich_run_detail
from acp_writer.services.sonataflow_client import (
    SonataFlowClient,
    map_to_run_detail,
    map_to_run_summary,
)

logger = logging.getLogger(__name__)

SONATAFLOW_URL = os.getenv("SONATAFLOW_URL", "")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "")
LLM_REASONING_URL = os.getenv("LLM_REASONING_URL", "http://acp-llm-reasoning:8080")
DECISION_ENGINE_URL = os.getenv("DECISION_ENGINE_URL", "http://acp-decision-engine:8080")
FHIR_SERVER_URL = os.getenv("FHIR_SERVER_URL", "http://acp-fhir-server:8080")

_phi_store: ArtifactStore | None = None
_artifacts_store: ArtifactStore | None = None
if MINIO_ENDPOINT:
    _ak = os.getenv("ARTIFACT_STORE_ACCESS_KEY", "minioadmin")
    _sk = os.getenv("ARTIFACT_STORE_SECRET_KEY", "minioadmin")
    _phi_store = ArtifactStore(
        endpoint_url=MINIO_ENDPOINT, bucket="cpg-phi",
        access_key=_ak, secret_key=_sk,
    )
    _artifacts_store = ArtifactStore(
        endpoint_url=MINIO_ENDPOINT, bucket="cpg-artifacts",
        access_key=_ak, secret_key=_sk,
    )

_sonataflow: SonataFlowClient | None = None
if SONATAFLOW_URL:
    _sonataflow = SonataFlowClient(SONATAFLOW_URL)

_http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))

app = FastAPI(title="acp-writer-bff", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "UP",
        "service": "bff",
        "minio": bool(_phi_store),
        "sonataflow": bool(SONATAFLOW_URL),
    }


# ---------------------------------------------------------------------------
# Notifications from cpg-ingester SonataFlow
# ---------------------------------------------------------------------------

@app.post("/api/v1/notifications/artifacts-available")
@mlflow.trace(name="bff.artifacts_available")
async def artifacts_available(request: Request):
    """Receive CPG artifact delivery notification from cpg-ingester.

    Pulls artifacts from MinIO and registers them with the appropriate
    backend pods so they are available for care plan generation.

    Expected payload (from cpg-ingester SonataFlow NotifyConsumers):
      {cpg_id, cpg_title, artifact_location, artifacts: [{type, ref, ...}]}
    """
    payload = await request.json()
    cpg_id = payload.get("cpg_id", "UNKNOWN")
    artifacts = payload.get("artifacts", [])
    logger.info("Received artifact notification for CPG %s (%d artifacts)", cpg_id, len(artifacts))

    results = {"cpg_id": cpg_id, "registered": [], "errors": []}

    for artifact in artifacts:
        art_type = artifact.get("type", "")
        ref = artifact.get("ref", "")
        if not ref:
            continue

        try:
            if art_type == "metadata":
                _register_metadata(ref)
                results["registered"].append({"type": "metadata", "ref": ref})

            elif art_type == "dmn":
                _register_dmn_model(ref, artifact.get("name", "unknown"))
                results["registered"].append({"type": "dmn", "ref": ref, "name": artifact.get("name")})

            elif art_type == "recommendations":
                count = _register_recommendations(ref, cpg_id)
                results["registered"].append({"type": "recommendations", "ref": ref, "count": count})

            else:
                logger.debug("Skipping artifact type %s (ref=%s)", art_type, ref)
        except Exception as exc:
            msg = f"Failed to register {art_type} artifact {ref}: {exc}"
            logger.error(msg)
            results["errors"].append(msg)

    logger.info(
        "CPG %s: registered %d artifacts, %d errors",
        cpg_id, len(results["registered"]), len(results["errors"]),
    )
    return results


def _register_metadata(ref: str) -> None:
    """Pull CPG metadata from MinIO and register with the llm-reasoning pod."""
    if not _artifacts_store:
        raise RuntimeError("No artifact store configured")
    metadata = _artifacts_store.get(ref)
    resp = http_requests.post(
        f"{LLM_REASONING_URL}/api/v1/guidelines",
        json=metadata,
        timeout=10,
    )
    resp.raise_for_status()
    logger.info("Registered CPG metadata: %s", metadata.get("cpg_id", "?"))


def _register_dmn_model(ref: str, name: str) -> None:
    """Pull DMN XML from MinIO and deploy to the decision-engine pod."""
    if not _artifacts_store:
        raise RuntimeError("No artifact store configured")
    dmn_xml = _artifacts_store.get_raw(ref)
    resp = http_requests.post(
        f"{DECISION_ENGINE_URL}/api/v1/decisions/models",
        data=dmn_xml,
        headers={"Content-Type": "application/xml"},
        timeout=10,
    )
    resp.raise_for_status()
    logger.info("Registered DMN model: %s", name)


def _register_recommendations(ref: str, cpg_id: str) -> int:
    """Pull recommendation bundle from MinIO and ingest into the llm-reasoning pod."""
    if not _artifacts_store:
        raise RuntimeError("No artifact store configured")
    bundle = _artifacts_store.get(ref)
    resp = http_requests.post(
        f"{LLM_REASONING_URL}/api/v1/knowledge/recommendations/batch",
        json=bundle,
        timeout=30,
    )
    resp.raise_for_status()
    count = len(bundle.get("recommendations", []))
    logger.info("Registered %d recommendations for CPG %s", count, cpg_id)
    return count


def _reload_cpg_artifacts() -> None:
    """Scan MinIO published/ prefix and re-register all CPG artifacts.

    Called at startup to survive pod restarts — any previously delivered
    CPGs are reloaded into the backend pods' in-memory stores.
    """
    if not _artifacts_store:
        return
    try:
        client = _artifacts_store._get_client()
        response = client.list_objects_v2(
            Bucket="cpg-artifacts", Prefix="published/", Delimiter="/",
        )
        prefixes = [p["Prefix"] for p in response.get("CommonPrefixes", [])]
    except Exception as exc:
        logger.warning("Could not scan MinIO for published CPGs: %s", exc)
        return

    for prefix in prefixes:
        cpg_id = prefix.rstrip("/").split("/")[-1]
        logger.info("Reloading CPG artifacts for %s", cpg_id)
        metadata_ref = f"cpg-artifacts:{prefix}metadata.json"
        try:
            _register_metadata(metadata_ref)
        except Exception as exc:
            logger.warning("Failed to reload metadata for %s: %s", cpg_id, exc)

        try:
            dmn_resp = client.list_objects_v2(
                Bucket="cpg-artifacts", Prefix=f"{prefix}dmn/",
            )
            for obj in dmn_resp.get("Contents", []):
                key = obj["Key"]
                name = key.rsplit("/", 1)[-1].removesuffix(".dmn")
                _register_dmn_model(f"cpg-artifacts:{key}", name)
        except Exception as exc:
            logger.warning("Failed to reload DMN models for %s: %s", cpg_id, exc)

        rec_ref = f"cpg-artifacts:{prefix}recommendations.json"
        try:
            _register_recommendations(rec_ref, cpg_id)
        except Exception as exc:
            logger.warning("Failed to reload recommendations for %s: %s", cpg_id, exc)


# ---------------------------------------------------------------------------
# SonataFlow review notification (no-op acknowledgment)
# ---------------------------------------------------------------------------

@app.post("/api/v1/notify-review")
def notify_review(payload: dict | None = None):
    """Called by SonataFlow when a review callback state is entered."""
    logger.info("Review notification: %s", payload)
    return {"status": "acknowledged"}


# ---------------------------------------------------------------------------
# Run management (SonataFlow-backed, async start)
# ---------------------------------------------------------------------------

# Pending runs: BFF-generated ID → tracking state.  Entries are promoted
# to SonataFlow-backed once the background start_workflow call returns.
_pending_runs: dict[str, dict] = {}


async def _start_workflow_background(run_id: str, ips_ref: str, patient_name: str) -> None:
    """Start SonataFlow workflow in the background and update the pending-run mapping."""
    try:
        assert _sonataflow is not None
        instance = await _sonataflow.start_workflow(ips_ref, patient_name, business_key=run_id)
        _pending_runs[run_id]["sonataflow_id"] = instance["id"]
        _pending_runs[run_id]["status"] = "running"
        logger.info("Run %s → SonataFlow instance %s", run_id, instance["id"])
    except Exception as exc:
        _pending_runs[run_id]["status"] = "error"
        _pending_runs[run_id]["error"] = str(exc)
        logger.error("Failed to start workflow for run %s: %s", run_id, exc)


def _pending_run_summary(pr: dict) -> dict:
    return {
        "runId": pr["run_id"],
        "status": "starting" if pr["status"] == "starting" else pr["status"],
        "patientName": pr.get("patient_name", "Unknown Patient"),
        "patientReference": "",
        "currentSteps": [],
        "careplanId": None,
        "createdAt": pr["created_at"],
        "updatedAt": pr["created_at"],
    }


def _pending_run_detail(pr: dict) -> dict:
    return {
        "runId": pr["run_id"],
        "status": "starting" if pr["status"] == "starting" else pr["status"],
        "createdAt": pr["created_at"],
        "updatedAt": pr["created_at"],
        "currentSteps": [],
        "steps": [],
        "awaitingReview": None,
        "carePlan": None,
        "reviewIteration": 0,
        "previousFeedback": None,
        "careplanId": None,
        "error": pr.get("error"),
        "workflowData": None,
    }


@app.post("/api/v1/runs", status_code=202)
@mlflow.trace(name="bff.create_run")
async def create_run(request: Request):
    """Accept an IPS bundle, store in MinIO, and start a SonataFlow workflow.

    Returns immediately with a run ID. The SonataFlow workflow is started
    in the background — the UI polls GET /runs/{id} for progress.
    """
    body = await request.json()
    ips_bundle = body.get("ipsBundle")
    if not ips_bundle:
        return JSONResponse(status_code=400, content={"message": "ipsBundle is required"})

    patient_name = _extract_patient_name(ips_bundle)
    run_id = uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    ips_ref = ""
    if _phi_store:
        ips_ref = _phi_store.put(f"{run_id}/ips_bundle.json", ips_bundle)

    _pending_runs[run_id] = {
        "run_id": run_id,
        "status": "starting",
        "sonataflow_id": None,
        "patient_name": patient_name,
        "ips_ref": ips_ref,
        "created_at": now,
        "error": None,
    }

    if _sonataflow:
        asyncio.create_task(_start_workflow_background(run_id, ips_ref or json.dumps(ips_bundle), patient_name))

    return {"runId": run_id, "status": "starting"}


def _resolve_sonataflow_id(run_id: str) -> str | None:
    """If run_id is a BFF pending-run ID, return its SonataFlow instance ID (if available)."""
    pr = _pending_runs.get(run_id)
    if pr:
        return pr.get("sonataflow_id")
    return None


@app.get("/api/v1/runs")
async def list_runs(status: str | None = None, limit: int = 50):
    summaries: list[dict] = []
    sf_ids_in_list: set[str] = set()

    if _sonataflow:
        instances = await _sonataflow.list_instances()
        sf_ids_in_list = {inst["id"] for inst in instances}
        for inst in instances:
            summary = map_to_run_summary(inst)
            # If this instance was started with a business key matching a pending run, use that ID
            for pr in _pending_runs.values():
                if pr.get("sonataflow_id") == inst["id"]:
                    summary["runId"] = pr["run_id"]
                    break
            summaries.append(summary)

    # Include pending runs not yet visible in SonataFlow
    for pr in _pending_runs.values():
        if not pr.get("sonataflow_id") or (pr.get("sonataflow_id") and _sonataflow and pr["sonataflow_id"] not in sf_ids_in_list):
            summaries.append(_pending_run_summary(pr))

    if status:
        summaries = [s for s in summaries if s["status"] == status]
    summaries.sort(key=lambda s: s.get("createdAt", ""), reverse=True)
    return summaries[:limit]


@app.get("/api/v1/runs/{run_id}")
async def get_run(run_id: str):
    # Check pending runs first
    pr = _pending_runs.get(run_id)
    if pr:
        sf_id = pr.get("sonataflow_id")
        if _sonataflow:
            # Try direct ID lookup first, then business key for in-flight workflows
            instance = None
            if sf_id:
                try:
                    instance = await _sonataflow.get_instance(sf_id)
                except Exception:
                    pass
            if not instance:
                try:
                    instance = await _sonataflow.get_instance_by_business_key(run_id)
                except Exception:
                    pass
            if instance:
                if not sf_id:
                    pr["sonataflow_id"] = instance["id"]
                    pr["status"] = "running"
                detail = map_to_run_detail(instance)
                detail["runId"] = run_id
                return enrich_run_detail(detail, _phi_store, _artifacts_store)
        return _pending_run_detail(pr)

    # Fall through to direct SonataFlow lookup (for runs created before this change)
    if not _sonataflow:
        return JSONResponse(status_code=503, content={"message": "SonataFlow not configured"})
    try:
        instance = await _sonataflow.get_instance(run_id)
    except Exception:
        return JSONResponse(status_code=404, content={"message": f"Run {run_id} not found"})
    detail = map_to_run_detail(instance)
    return enrich_run_detail(detail, _phi_store, _artifacts_store)


@app.post("/api/v1/runs/{run_id}/review/{gate}")
@mlflow.trace(name="bff.submit_review")
async def submit_review(run_id: str, gate: str, request: Request):
    if gate != "careplan":
        return JSONResponse(status_code=400, content={"message": f"Unknown gate: {gate}"})
    if not _sonataflow:
        return JSONResponse(status_code=503, content={"message": "SonataFlow not configured"})

    sf_id = _resolve_sonataflow_id(run_id) or run_id
    try:
        instance = await _sonataflow.get_instance(sf_id)
    except Exception:
        return JSONResponse(status_code=404, content={"message": f"Run {run_id} not found"})

    pre_detail = map_to_run_detail(instance)
    if pre_detail.get("awaitingReview") != gate:
        return JSONResponse(status_code=409, content={"message": "Run is not awaiting careplan review"})

    review = await request.json()
    await _sonataflow.send_review(sf_id, gate, review or {})

    try:
        updated = await _sonataflow.get_instance(sf_id)
        updated_detail = map_to_run_detail(updated)
        updated_detail["runId"] = run_id
        enriched = enrich_run_detail(updated_detail, _phi_store, _artifacts_store)
        return JSONResponse(status_code=202, content=enriched)
    except Exception:
        return JSONResponse(status_code=202, content={"runId": run_id, "status": "running", "steps": []})


@app.delete("/api/v1/runs/{run_id}")
async def cancel_run(run_id: str):
    if not _sonataflow:
        return JSONResponse(status_code=503, content={"message": "SonataFlow not configured"})
    sf_id = _resolve_sonataflow_id(run_id) or run_id
    try:
        await _sonataflow.abort_instance(sf_id)
    except Exception:
        return JSONResponse(status_code=404, content={"message": f"Run {run_id} not found"})
    pr = _pending_runs.get(run_id)
    if pr:
        pr["status"] = "cancelled"
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Artifact proxy (MinIO)
# ---------------------------------------------------------------------------

@app.get("/api/v1/runs/{run_id}/artifacts/{path:path}")
def get_artifact(run_id: str, path: str):
    store = _phi_store or _artifacts_store
    if not store:
        return JSONResponse(status_code=503, content={"message": "No artifact store configured"})
    key = f"{run_id}/{path}"
    try:
        data = store.get_raw(key)
    except Exception:
        return JSONResponse(status_code=404, content={"message": f"Artifact not found: {key}"})
    return Response(content=data, media_type="application/octet-stream")


# ---------------------------------------------------------------------------
# Care plan proxy (fhir-server pod)
# ---------------------------------------------------------------------------

@app.get("/api/v1/careplans")
async def list_careplans(patient: str | None = None, status: str | None = None):
    params = {}
    if patient:
        params["patient"] = patient
    if status:
        params["status"] = status
    try:
        resp = await _http.get(f"{FHIR_SERVER_URL}/api/v1/careplans", params=params)
        resp.raise_for_status()
        raw_plans = resp.json()
    except Exception as exc:
        logger.error("Failed to list care plans: %s", exc)
        return JSONResponse(status_code=502, content={"message": "Failed to reach FHIR server"})
    return [_to_careplan_summary(cp) for cp in (raw_plans if isinstance(raw_plans, list) else [])]


@app.get("/api/v1/careplans/{careplan_id}")
async def get_careplan(careplan_id: str):
    try:
        resp = await _http.get(f"{FHIR_SERVER_URL}/api/v1/careplans/{careplan_id}")
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        logger.error("Failed to get care plan %s: %s", careplan_id, exc)
        return JSONResponse(status_code=502, content={"message": "Failed to reach FHIR server"})
    if not raw:
        return JSONResponse(status_code=404, content={"message": f"Care plan {careplan_id} not found"})
    return _to_careplan_detail(raw)


# ---------------------------------------------------------------------------
# System status
# ---------------------------------------------------------------------------

@app.get("/api/v1/status")
async def system_status():
    result: dict = {
        "version": "0.1.0",
        "decisionEngine": {"available": False, "modelsDeployed": 0},
        "knowledgeBase": {"available": False, "guidelines": 0, "recommendations": 0},
    }
    try:
        resp = await _http.get(f"{LLM_REASONING_URL}/api/v1/status", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            de = data.get("decision_engine", {})
            kb = data.get("knowledge_base", {})
            result["decisionEngine"] = {
                "available": de.get("status") == "healthy",
                "modelsDeployed": de.get("models_deployed", 0),
            }
            result["knowledgeBase"] = {
                "available": kb.get("status") == "healthy",
                "guidelines": kb.get("guidelines_registered", 0),
                "recommendations": kb.get("recommendations_ingested", 0),
            }
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_patient_name(ips_bundle: dict) -> str:
    """Extract patient name from a FHIR IPS bundle."""
    for entry in ips_bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Patient":
            for name in resource.get("name", []):
                parts = []
                if name.get("given"):
                    parts.extend(name["given"])
                if name.get("family"):
                    parts.append(name["family"])
                if parts:
                    return " ".join(parts)
    return "Unknown Patient"


def _extract_patient_name_from_bundle(bundle: dict) -> str:
    """Extract patient display name from a stored FHIR care-plan bundle."""
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Patient":
            for name in resource.get("name", []):
                parts = []
                if name.get("given"):
                    parts.extend(name["given"])
                if name.get("family"):
                    parts.append(name["family"])
                if parts:
                    return " ".join(parts)
    return ""


def _to_careplan_summary(raw: dict) -> dict:
    """Shape a raw care-plan record into a CarePlanSummary view-model."""
    return {
        "id": raw.get("id", ""),
        "patientName": raw.get("patient_name", ""),
        "patientReference": raw.get("patient_reference", ""),
        "status": raw.get("status", ""),
        "generatedAt": raw.get("generated_at"),
        "runId": raw.get("run_id"),
    }


def _to_careplan_detail(raw: dict) -> dict:
    """Shape a raw care-plan record into a CarePlanDetail view-model."""
    bundle = raw.get("bundle", {})
    summary = _to_careplan_summary(raw)
    patient_name = summary["patientName"] or _extract_patient_name_from_bundle(bundle)
    if patient_name:
        summary["patientName"] = patient_name

    patient = _extract_patient_from_bundle(bundle)
    goals, activities, conflicts = _extract_view_from_bundle(bundle)

    return {
        **summary,
        "patient": patient,
        "view": {
            "goals": goals,
            "activities": activities,
            "conflicts": conflicts,
            "fhirBundle": bundle if bundle.get("entry") else None,
        },
    }


def _extract_patient_from_bundle(bundle: dict) -> dict | None:
    """Extract PatientSummary from a stored FHIR care-plan bundle."""
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Patient":
            name = ""
            for n in resource.get("name", []):
                if isinstance(n, dict):
                    text = n.get("text")
                    if text:
                        name = text
                        break
                    parts = []
                    if n.get("given"):
                        parts.extend(n["given"])
                    if n.get("family"):
                        parts.append(n["family"])
                    if parts:
                        name = " ".join(parts)
                        break
            return {
                "name": name,
                "birthDate": resource.get("birthDate", ""),
                "gender": resource.get("gender", ""),
                "patientReference": "",
                "conditions": [],
                "medications": [],
                "allergies": [],
                "observations": [],
            }
    return None


def _extract_view_from_bundle(bundle: dict) -> tuple[list, list, list]:
    """Extract goals, activities, and conflicts from a FHIR CarePlan bundle."""
    entries = bundle.get("entry", [])
    resources = {
        e.get("fullUrl", ""): e.get("resource", {})
        for e in entries
    }

    source_cpgs = _extract_source_cpgs(resources)

    goals = []
    for url, r in resources.items():
        if r.get("resourceType") == "Goal":
            target_text = _format_goal_target(r.get("target", []))
            goals.append({
                "id": r.get("id", ""),
                "description": r.get("description", {}).get("text", ""),
                "rationale": target_text or None,
                "sourceCpgId": source_cpgs.get(url),
            })

    activities = []
    for url, r in resources.items():
        rt = r.get("resourceType")
        if rt == "MedicationRequest":
            activities.append({
                "id": r.get("id", ""),
                "description": r.get("medicationCodeableConcept", {}).get("text", ""),
                "goalId": None,
                "detail": "; ".join(d.get("text", "") for d in r.get("dosageInstruction", [])),
            })
        elif rt == "ServiceRequest":
            activities.append({
                "id": r.get("id", ""),
                "description": r.get("code", {}).get("text", ""),
                "goalId": None,
                "detail": "; ".join(n.get("text", "") for n in r.get("note", [])),
            })

    careplan = next((r for r in resources.values() if r.get("resourceType") == "CarePlan"), {})
    for act in careplan.get("activity", []):
        detail = act.get("detail")
        if detail and not act.get("reference"):
            activities.append({
                "id": detail.get("code", {}).get("text", "")[:8],
                "description": detail.get("description", ""),
                "goalId": None,
                "detail": None,
            })

    return goals, activities, []


def _format_goal_target(targets: list) -> str:
    """Format Goal.target[] into a human-readable string."""
    parts = []
    for t in targets:
        measure = t.get("measure", {}).get("text", "")
        detail_range = t.get("detailRange", {})
        low = detail_range.get("low", {})
        high = detail_range.get("high", {})
        if measure:
            if high and low:
                parts.append(f"Target {measure}: {low.get('value')}–{high.get('value')} {high.get('unit', '')}")
            elif high:
                parts.append(f"Target {measure}: < {high.get('value')} {high.get('unit', '')}")
            elif low:
                parts.append(f"Target {measure}: > {low.get('value')} {low.get('unit', '')}")
            else:
                parts.append(f"Target: {measure}")
    return "; ".join(parts)


def _extract_source_cpgs(resources: dict) -> dict:
    """Map resource fullUrls to source CPG IDs from Provenance resources."""
    cpg_map: dict[str, str] = {}
    for r in resources.values():
        if r.get("resourceType") != "Provenance":
            continue
        cpg_names = []
        for entity in r.get("entity", []):
            if entity.get("role") == "derivation":
                display = entity.get("what", {}).get("display", "")
                if display.startswith("CPG: "):
                    cpg_names.append(display[5:])
        if cpg_names:
            cpg_str = ", ".join(cpg_names)
            for target in r.get("target", []):
                ref = target.get("reference", "")
                if ref:
                    cpg_map[ref] = cpg_str
    return cpg_map


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _on_startup():
    logger.info(
        "acp-writer BFF starting (sonataflow=%s, minio=%s)",
        bool(SONATAFLOW_URL), bool(MINIO_ENDPOINT),
    )
    _reload_cpg_artifacts()


@app.on_event("shutdown")
async def _on_shutdown():
    await _http.aclose()
    if _sonataflow:
        await _sonataflow.close()
