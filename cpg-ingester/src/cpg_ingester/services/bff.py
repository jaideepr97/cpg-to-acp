"""BFF (Backend-for-Frontend) service for the cpg-ingester React UI.

Mediates between the SPA and SonataFlow/MinIO. Falls back to mock data
automatically when no backend infrastructure is configured.
"""

import logging
import os

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

SONATAFLOW_URL = os.getenv("SONATAFLOW_URL", "")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "")
DATA_INDEX_URL = os.getenv("DATA_INDEX_URL", "")

_backend_configured = bool(SONATAFLOW_URL and MINIO_ENDPOINT)

app = FastAPI(title="cpg-ingester-bff", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_mock_mode = False

if not _backend_configured:
    try:
        from cpg_ingester.mocks.router import router as mock_router
        app.include_router(mock_router)
        _mock_mode = True
        logger.info("No SONATAFLOW_URL/MINIO_ENDPOINT configured — serving mock data")
    except ImportError:
        logger.warning("No backend configured and mocks package not available")


@app.get("/health")
def health():
    return {"status": "UP", "service": "bff", "mock": _mock_mode}


# ---------------------------------------------------------------------------
# Production endpoints — wired to SonataFlow / MinIO / Data Index
# These are only active when mock mode is OFF (mock router takes precedence
# when included, since it registers the same paths first).
# ---------------------------------------------------------------------------

if not _mock_mode:

    @app.get("/api/v1/runs")
    def list_runs():
        # TODO: proxy to SonataFlow / Data Index
        return []

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str):
        # TODO: query Data Index GraphQL + MinIO artifacts
        return {}

    @app.post("/api/v1/upload")
    async def upload_cpg(pdf: UploadFile = File(...)):
        # TODO: store in MinIO, start SonataFlow workflow
        return {"runId": ""}

    @app.post("/api/v1/runs/{run_id}/review/{gate}")
    async def submit_review(run_id: str, gate: str):
        # TODO: send CloudEvent to SonataFlow
        return {"status": "accepted"}

    @app.post("/api/v1/runs/{run_id}/rerun")
    async def rerun_pipeline(run_id: str):
        # TODO: read original pdf_ref, create new workflow instance
        return {"runId": ""}

    @app.get("/api/v1/runs/{run_id}/artifacts/{path:path}")
    def get_artifact(run_id: str, path: str):
        # TODO: fetch from MinIO
        return {}
