"""BFF (Backend-for-Frontend) service for the cpg-ingester React UI.

Mediates between the SPA and SonataFlow/MinIO. Each backend dependency
is independently optional — MinIO can be configured without SonataFlow
and vice versa. Endpoints that lack their backing service fall back to
mock data when available.
"""

import logging
import os
from uuid import uuid4

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from cpg_contracts.artifact_store import ArtifactStore

from cpg_ingester.services.artifact_resolver import enrich_run_detail
from cpg_ingester.services.sonataflow_client import (
    SonataFlowClient,
    map_to_run_detail,
    map_to_run_summary,
)

logger = logging.getLogger(__name__)

SONATAFLOW_URL = os.getenv("SONATAFLOW_URL", "")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "")
DATA_INDEX_URL = os.getenv("DATA_INDEX_URL", "")

_artifact_store: ArtifactStore | None = None
if MINIO_ENDPOINT:
    _artifact_store = ArtifactStore(
        endpoint_url=MINIO_ENDPOINT,
        bucket="cpg-uploads",
        access_key=os.getenv("ARTIFACT_STORE_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("ARTIFACT_STORE_SECRET_KEY", "minioadmin"),
    )

_sonataflow: SonataFlowClient | None = None
if SONATAFLOW_URL:
    _sonataflow = SonataFlowClient(SONATAFLOW_URL)

app = FastAPI(title="cpg-ingester-bff", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/v1/notify-review")
def notify_review(payload: dict | None = None):
    """Called by SonataFlow when a review callback state is entered.

    No-op acknowledgment — the UI discovers review state by polling.
    """
    logger.info("Review notification: %s", payload)
    return {"status": "acknowledged"}


@app.get("/health")
def health():
    return {
        "status": "UP",
        "service": "bff",
        "minio": bool(_artifact_store),
        "sonataflow": bool(SONATAFLOW_URL),
    }


# ---------------------------------------------------------------------------
# MinIO-backed endpoints (upload, artifacts) — registered first so they
# take priority over mock router paths when MinIO is configured
# ---------------------------------------------------------------------------

if _artifact_store:

    @app.post("/api/v1/upload")
    async def upload_cpg(pdf: UploadFile = File(...)):
        upload_id = uuid4().hex[:8]
        filename = pdf.filename or "document.pdf"
        key = f"uploads/{upload_id}/{filename}"
        content = await pdf.read()
        content_type = pdf.content_type or "application/pdf"
        pdf_ref = _artifact_store.put_raw(key, content, content_type)
        logger.info("Uploaded %s (%d bytes) -> %s", filename, len(content), pdf_ref)

        if _sonataflow:
            instance = _sonataflow.start_workflow(pdf_ref, filename)
            run_id = instance["id"]
            logger.info("Started SonataFlow workflow %s for %s", run_id, filename)
        else:
            run_id = f"run-{upload_id}"

        return {"runId": run_id}

    @app.get("/api/v1/runs/{run_id}/artifacts/{path:path}")
    def get_artifact(run_id: str, path: str):
        key = f"{run_id}/{path}"
        try:
            data = _artifact_store.get_raw(key)
        except Exception:
            return JSONResponse(status_code=404, content={"error": f"Artifact not found: {key}"})
        return Response(content=data, media_type="application/octet-stream")


# ---------------------------------------------------------------------------
# Mock fallback for SonataFlow-dependent endpoints (runs, reviews).
# Registered after MinIO endpoints so real upload/artifact routes win.
# ---------------------------------------------------------------------------
_mock_mode = False
if not SONATAFLOW_URL:
    try:
        from cpg_ingester.mocks.router import router as mock_router
        app.include_router(mock_router)
        _mock_mode = True
        logger.info("No SONATAFLOW_URL configured — serving mock run/review data")
    except ImportError:
        logger.warning("No SonataFlow configured and mocks package not available")


# ---------------------------------------------------------------------------
# SonataFlow-backed endpoints (runs, reviews) — only when not mocked
# ---------------------------------------------------------------------------

if not _mock_mode:

    @app.get("/api/v1/runs")
    def list_runs():
        instances = _sonataflow.list_instances()
        return [map_to_run_summary(inst) for inst in instances]

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str):
        try:
            instance = _sonataflow.get_instance(run_id)
        except Exception:
            return JSONResponse(status_code=404, content={"error": f"Run {run_id} not found"})
        detail = map_to_run_detail(instance)
        return enrich_run_detail(detail, _artifact_store)

    @app.post("/api/v1/runs/{run_id}/review/{gate}")
    async def submit_review(run_id: str, gate: str, request: Request):
        if gate not in ("manifest", "pre-delivery"):
            return JSONResponse(status_code=400, content={"error": f"Unknown gate: {gate}"})
        review = await request.json()
        _sonataflow.send_review(run_id, gate, review or {})
        return {"status": "accepted"}

    @app.delete("/api/v1/runs/{run_id}")
    def cancel_run(run_id: str):
        try:
            _sonataflow.cancel_instance(run_id)
        except Exception:
            logger.exception("Failed to cancel run %s", run_id)
            return JSONResponse(status_code=404, content={"error": f"Run {run_id} not found"})
        return {"status": "cancelled"}

    @app.post("/api/v1/runs/{run_id}/rerun")
    def rerun_pipeline(run_id: str):
        try:
            original = _sonataflow.get_instance(run_id)
        except Exception:
            return JSONResponse(status_code=404, content={"error": f"Run {run_id} not found"})
        data = original.get("workflowdata", {})
        pdf_ref = data.get("pdf_ref", "")
        cpg_name = data.get("cpg_name", "Rerun")
        instance = _sonataflow.start_workflow(pdf_ref, cpg_name)
        return {"runId": instance["id"]}
