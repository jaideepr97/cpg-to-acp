"""LLM Analysis pod service — all LLM-calling nodes with in-process LangGraph review loops.

Consumes: parse_result_ref. Produces: analysis_result_ref.
Security profile: LLM inference endpoint only (via MaaS on OpenShift).
"""

import logging
import os
import tempfile
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Request

from cpg_contracts import get_artifact_store, post_callback, resolve_ref, store_artifact
from cpg_ingester.nodes.content_filter import content_filter
from cpg_ingester.nodes.item_identifier import item_identifier
from cpg_ingester.nodes.classification_reviewer import classification_reviewer
from cpg_ingester.nodes.metadata_extractor import metadata_extractor
from cpg_ingester.nodes.structure_analyzer import structure_analyzer

logger = logging.getLogger(__name__)

app = FastAPI(title="cpg-ingester-llm-analysis", version="0.1.0")
_store = get_artifact_store()

MAX_CLASSIFICATION_REVIEWS = 2

LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
LLM_MODEL = os.environ.get("LLM_MODEL", "default")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-change-me")


@app.get("/health")
def health():
    return {"status": "UP", "service": "llm-analysis"}


def _do_analyze(data: dict) -> dict:
    """Run the full LLM analysis. Used by both sync and async endpoints."""
    parse_result = resolve_ref(data, "parse_result", _store)
    if isinstance(parse_result, dict) and "markdown" in parse_result:
        markdown = parse_result["markdown"]
        docling_json = parse_result.get("docling_json", {})
    else:
        markdown = data.get("markdown", "")
        docling_json = data.get("docling_json", {})

    with tempfile.TemporaryDirectory() as output_dir:
        state = {
            "markdown": markdown,
            "docling_json": docling_json,
            "output_dir": output_dir,
            "litellm_url": LITELLM_URL,
            "llm_model": LLM_MODEL,
            "llm_api_key": LLM_API_KEY,
        }

        updates = structure_analyzer(state)
        state.update(updates)

        updates = content_filter(state)
        state.update(updates)

        for _ in range(MAX_CLASSIFICATION_REVIEWS + 1):
            updates = item_identifier(state)
            state.update(updates)

            updates = classification_reviewer(state)
            state.update(updates)

            if not state.get("classification_review_feedback"):
                break
            if state.get("classification_review_count", 0) >= MAX_CLASSIFICATION_REVIEWS:
                break

        updates = metadata_extractor(state)
        state.update(updates)

        from cpg_ingester.generation import generate_all
        updates = generate_all(state)
        state.update(updates)

        result = {
            "section_map": state.get("section_map", []),
            "abbreviations": state.get("abbreviations", {}),
            "grading_definitions": state.get("grading_definitions", ""),
            "archetype": state.get("archetype", ""),
            "item_manifest": state.get("item_manifest", []),
            "cpg_metadata": state.get("cpg_metadata", {}),
            "dmn_results": state.get("dmn_results", []),
            "recommendation_results": state.get("recommendation_results", []),
        }

        _, ref = store_artifact(_store, f"{uuid4()}/analysis_result.json", result)
        if ref:
            return {"analysis_result_ref": ref}
        if _store:
            raise RuntimeError("Artifact store available but failed to store analysis result")
        return result


@app.post("/api/v1/analyze")
async def analyze(request: Request):
    """Run the full LLM analysis phase (sync)."""
    data = await request.json()
    return _do_analyze(data)


@app.post("/api/v1/analyze-async")
async def analyze_async(request: Request, background_tasks: BackgroundTasks):
    """Async version: accept immediately, run analysis in background, POST callback."""
    data = await request.json()
    callback_url = data.pop("callback_url", "")
    process_instance_id = data.pop("process_instance_id", "")
    background_tasks.add_task(
        _run_analyze_background, data, callback_url, process_instance_id
    )
    return {"status": "accepted"}


def _run_analyze_background(data: dict, callback_url: str, process_instance_id: str):
    try:
        result = _do_analyze(data)
    except Exception as e:
        logger.error("Analyze background task failed: %s", e)
        result = {"error": str(e)}

    post_callback(callback_url, process_instance_id, "analyze-done", result)
