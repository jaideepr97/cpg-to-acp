"""LLM Reasoning pod service — Guideline Resolver, Recommendation Retriever,
Plan Composer with Brief Reviewer loop, FHIR Semantic Reviewer.

Also handles CPG artifact management (guidelines, recommendations) since
the vector store and guidelines registry live in this pod's process.

Security profile: LLM inference + vector store, no FHIR server access.
"""

import logging
import os
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from cpg_contracts import (
    CPGMetadata,
    Recommendation,
    RecommendationBundle,
    RecommendationSearchRequest,
    get_artifact_store,
    get_phi_store,
    post_callback,
    resolve_ref,
    store_artifact,
)
from acp_writer.api import _guidelines_store, _vector_store
from acp_writer.nodes.guideline_resolver import guideline_resolver
from acp_writer.nodes.recommendation_retriever import recommendation_retriever
from acp_writer.nodes.plan_composer import plan_composer
from acp_writer.nodes.brief_reviewer import brief_reviewer
from acp_writer.nodes.fhir_semantic_reviewer import fhir_semantic_reviewer
from acp_writer.pipeline import MAX_BRIEF_REVIEWS

logger = logging.getLogger(__name__)

app = FastAPI(title="acp-writer-llm-reasoning", version="0.1.0")
_store = get_artifact_store()
_phi_store = get_phi_store()

LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
LLM_MODEL = os.environ.get("LLM_MODEL", "default")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-change-me")


@app.get("/health")
def health():
    return {"status": "UP", "service": "llm-reasoning"}


# --- CPG artifact management (used by cpg-ingester Delivery) ---


@app.post("/api/v1/guidelines", status_code=201)
async def register_guideline(request: Request):
    data = await request.json()
    metadata = CPGMetadata.model_validate(data)
    result = _guidelines_store.register(metadata)
    return result.model_dump(mode="json")


@app.post("/api/v1/knowledge/recommendations/batch", status_code=201)
async def ingest_recommendation_batch(request: Request):
    data = await request.json()
    bundle = RecommendationBundle.model_validate(data)
    _vector_store.add_batch(bundle.recommendations)
    return {
        "source_cpg": bundle.source_cpg,
        "count": len(bundle.recommendations),
        "status": "ingested",
    }


@app.post("/api/v1/knowledge/search")
async def search_knowledge(request: Request):
    data = await request.json()
    search_req = RecommendationSearchRequest.model_validate(data)
    result = _vector_store.search(search_req)
    return result.model_dump(mode="json")


# --- Pipeline execution endpoints ---


@app.post("/api/v1/resolve")
async def resolve(request: Request):
    """Resolve applicable guidelines for patient conditions."""
    data = await request.json()
    state = {
        "condition_codes": data.get("condition_codes", []),
        "litellm_url": LITELLM_URL,
        "llm_model": LLM_MODEL,
        "llm_api_key": LLM_API_KEY,
    }
    result = guideline_resolver(state)
    return {
        "applicable_cpgs": result.get("applicable_cpgs", []),
        "applicable_dmn_models": result.get("applicable_dmn_models", []),
        "dmn_dependency_graph": result.get("dmn_dependency_graph", []),
    }


@app.post("/api/v1/retrieve")
async def retrieve(request: Request):
    """Retrieve recommendations from vector store."""
    data = await request.json()
    state = {
        "condition_codes": data.get("condition_codes", []),
        "dmn_results": data.get("dmn_results", []),
        "applicable_cpgs": data.get("applicable_cpgs", []),
    }
    result = recommendation_retriever(state)
    recs = result.get("recommendations", [])

    _, ref = store_artifact(_store, f"{uuid4()}/recommendations.json", recs)
    if ref:
        return {"recommendations_ref": ref}
    return {"recommendations": recs}


@app.post("/api/v1/compose")
async def compose(request: Request):
    """Run Plan Composer with Brief Reviewer loop."""
    data = await request.json()
    recommendations = resolve_ref(data, "recommendations", _store)
    state = {
        "patient_reference": data.get("patient_reference", ""),
        "patient_demographics": data.get("patient_demographics", {}),
        "condition_codes": data.get("condition_codes", []),
        "medication_codes": data.get("medication_codes", []),
        "allergy_codes": data.get("allergy_codes", []),
        "dmn_results": data.get("dmn_results", []),
        "recommendations": recommendations if isinstance(recommendations, list) else [],
        "applicable_cpgs": data.get("applicable_cpgs", []),
        "litellm_url": LITELLM_URL,
        "llm_model": LLM_MODEL,
        "llm_api_key": LLM_API_KEY,
        "brief_review_count": 0,
        "brief_review_feedback": "",
    }

    for _ in range(MAX_BRIEF_REVIEWS + 1):
        updates = plan_composer(state)
        state.update(updates)

        updates = brief_reviewer(state)
        state.update(updates)

        if not state.get("brief_review_feedback"):
            break
        if state.get("brief_review_count", 0) >= MAX_BRIEF_REVIEWS:
            break

    brief = state.get("planning_brief", {})
    _, ref = store_artifact(_phi_store, f"{uuid4()}/planning_brief.json", brief)
    if ref:
        return {"planning_brief_ref": ref}
    return {"planning_brief": brief}


@app.post("/api/v1/compose-async")
async def compose_async(request: Request, background_tasks: BackgroundTasks):
    """Async version: accept immediately, run compose in background, POST callback."""
    data = await request.json()
    callback_url = data.pop("callback_url", "")
    process_instance_id = data.pop("process_instance_id", "")
    background_tasks.add_task(_run_compose_background, data, callback_url, process_instance_id)
    return {"status": "accepted"}


def _run_compose_background(data: dict, callback_url: str, process_instance_id: str):
    try:
        recommendations = resolve_ref(data, "recommendations", _store)
        state = {
            "patient_reference": data.get("patient_reference", ""),
            "patient_demographics": data.get("patient_demographics", {}),
            "condition_codes": data.get("condition_codes", []),
            "medication_codes": data.get("medication_codes", []),
            "allergy_codes": data.get("allergy_codes", []),
            "dmn_results": data.get("dmn_results", []),
            "recommendations": recommendations if isinstance(recommendations, list) else [],
            "applicable_cpgs": data.get("applicable_cpgs", []),
            "litellm_url": LITELLM_URL,
            "llm_model": LLM_MODEL,
            "llm_api_key": LLM_API_KEY,
            "brief_review_count": 0,
            "brief_review_feedback": "",
        }

        for _ in range(MAX_BRIEF_REVIEWS + 1):
            updates = plan_composer(state)
            state.update(updates)
            updates = brief_reviewer(state)
            state.update(updates)
            if not state.get("brief_review_feedback"):
                break
            if state.get("brief_review_count", 0) >= MAX_BRIEF_REVIEWS:
                break

        brief = state.get("planning_brief", {})
        _, ref = store_artifact(_phi_store, f"{uuid4()}/planning_brief.json", brief)
        if ref:
            result = {"planning_brief_ref": ref}
        elif _phi_store:
            raise RuntimeError("Artifact store available but failed to store planning brief")
        else:
            result = {"planning_brief": brief}
    except Exception as e:
        logger.error("Compose background task failed: %s", e)
        result = {"error": str(e)}

    post_callback(callback_url, process_instance_id, "compose-done", result)


@app.post("/api/v1/review-fhir")
async def review_fhir(request: Request):
    """Run FHIR Semantic Reviewer."""
    data = await request.json()
    fhir_bundle = resolve_ref(data, "fhir_bundle", _phi_store)
    state = {
        "fhir_bundle": fhir_bundle,
        "terminology_issues": data.get("terminology_issues", []),
        "syntax_errors": data.get("syntax_errors", []),
        "fhir_review_count": data.get("fhir_review_count", 0),
        "litellm_url": LITELLM_URL,
        "llm_model": LLM_MODEL,
        "llm_api_key": LLM_API_KEY,
    }
    result = fhir_semantic_reviewer(state)
    return {
        "fhir_review_feedback": result.get("fhir_review_feedback", ""),
        "fhir_review_count": result.get("fhir_review_count", 0),
    }


@app.post("/api/v1/review-fhir-async")
async def review_fhir_async(request: Request, background_tasks: BackgroundTasks):
    """Async version: accept immediately, run review in background, POST callback."""
    data = await request.json()
    callback_url = data.pop("callback_url", "")
    process_instance_id = data.pop("process_instance_id", "")
    background_tasks.add_task(_run_review_fhir_background, data, callback_url, process_instance_id)
    return {"status": "accepted"}


def _run_review_fhir_background(data: dict, callback_url: str, process_instance_id: str):
    try:
        fhir_bundle = resolve_ref(data, "fhir_bundle", _phi_store)
        state = {
            "fhir_bundle": fhir_bundle,
            "terminology_issues": data.get("terminology_issues", []),
            "syntax_errors": data.get("syntax_errors", []),
            "fhir_review_count": data.get("fhir_review_count", 0),
            "litellm_url": LITELLM_URL,
            "llm_model": LLM_MODEL,
            "llm_api_key": LLM_API_KEY,
        }
        result_state = fhir_semantic_reviewer(state)
        result = {
            "fhir_review_feedback": result_state.get("fhir_review_feedback", ""),
            "fhir_review_count": result_state.get("fhir_review_count", 0),
        }
    except Exception as e:
        logger.error("Review-FHIR background task failed: %s", e)
        result = {"error": str(e), "fhir_review_feedback": "", "fhir_review_count": 0}

    post_callback(callback_url, process_instance_id, "review-done", result)
