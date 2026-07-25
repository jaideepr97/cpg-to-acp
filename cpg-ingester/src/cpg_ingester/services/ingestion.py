"""Ingestion pod service — Docling PDF parsing.

Produces: parse_result_ref (stores markdown + docling_json in MinIO).
Security profile: filesystem + ML models, no external network.
"""

import logging
import os
import tempfile
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Request, UploadFile

from cpg_contracts import get_artifact_store, post_callback, store_artifact
from cpg_ingester.nodes.docling_agent import docling_agent

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)-5s %(name)s: %(message)s", force=True)
logger = logging.getLogger(__name__)

app = FastAPI(title="cpg-ingester-ingestion", version="0.1.0")
_store = get_artifact_store()


@app.get("/health")
def health():
    return {"status": "UP", "service": "ingestion"}


@app.post("/api/v1/parse")
async def parse_pdf(file: UploadFile = File(...)):
    """Parse a CPG PDF into markdown and Docling JSON (sync)."""
    pdf_bytes = await file.read()
    return _do_parse_bytes(pdf_bytes, file.filename or "input.pdf")


@app.post("/api/v1/parse-async")
async def parse_pdf_async(request: Request, background_tasks: BackgroundTasks):
    """Async version: accept JSON with pdf_ref (MinIO key), parse in background."""
    data = await request.json()
    callback_url = data.get("callback_url", "")
    process_instance_id = data.get("process_instance_id", "")
    pdf_ref = data.get("pdf_ref", "")
    background_tasks.add_task(
        _run_parse_background, pdf_ref, callback_url, process_instance_id
    )
    return {"status": "accepted"}


def _do_parse_bytes(pdf_bytes: bytes, filename: str = "input.pdf") -> dict:
    """Run Docling parsing on raw bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, filename)
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        output_dir = os.path.join(tmpdir, "output")
        os.makedirs(output_dir)

        result = docling_agent({
            "pdf_path": pdf_path,
            "output_dir": output_dir,
        })

        parse_output = {
            "markdown": result.get("markdown", ""),
            "docling_json": result.get("docling_json", {}),
        }

        _, ref = store_artifact(_store, f"{uuid4()}/parse_result.json", parse_output)
        if ref:
            return {"parse_result_ref": ref}
        if _store:
            raise RuntimeError("Artifact store available but failed to store parse result")
        return parse_output


def _run_parse_background(
    pdf_ref: str, callback_url: str, process_instance_id: str
):
    try:
        if _store and pdf_ref:
            pdf_bytes = _store.get_raw(pdf_ref)
        else:
            post_callback(callback_url, process_instance_id, "parse-done",
                          {"error": "No artifact store or pdf_ref provided"})
            return

        result = _do_parse_bytes(pdf_bytes)
    except Exception as e:
        logger.error("Parse background task failed: %s", e)
        result = {"error": str(e)}

    post_callback(callback_url, process_instance_id, "parse-done", result)
