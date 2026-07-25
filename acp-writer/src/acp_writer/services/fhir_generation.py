"""FHIR Generation pod service — Bundle Generator + validators.

Consumes: planning_brief_ref. Produces: fhir_bundle_ref.
Security profile: terminology API access + LLM inference (bundle generation).
"""

import logging
import os
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Request

from cpg_contracts import get_phi_store, post_callback, resolve_ref, store_artifact
from acp_writer.nodes.fhir_bundle_generator import fhir_bundle_generator
from acp_writer.nodes.terminology_validator import terminology_validator
from acp_writer.nodes.fhir_syntax_validator import fhir_syntax_validator

logger = logging.getLogger(__name__)

app = FastAPI(title="acp-writer-fhir-generation", version="0.1.0")
_phi_store = get_phi_store()

LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
LLM_MODEL = os.environ.get("LLM_MODEL", "default")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-change-me")


@app.get("/health")
def health():
    return {"status": "UP", "service": "fhir-generation"}


@app.post("/api/v1/generate-bundle")
async def generate_bundle(request: Request):
    """Generate FHIR Bundle from Planning Brief, then validate."""
    data = await request.json()
    planning_brief = resolve_ref(data, "planning_brief", _phi_store)
    state = {
        "planning_brief": planning_brief,
        "patient_demographics": data.get("patient_demographics", {}),
        "fhir_review_feedback": data.get("fhir_review_feedback", ""),
        "litellm_url": LITELLM_URL,
        "llm_model": LLM_MODEL,
        "llm_api_key": LLM_API_KEY,
    }

    gen_result = fhir_bundle_generator(state)
    state.update(gen_result)

    term_result = terminology_validator(state)
    syntax_result = fhir_syntax_validator(state)

    fhir_bundle = state.get("fhir_bundle", {})
    _, ref = store_artifact(_phi_store, f"{uuid4()}/fhir_bundle.json", fhir_bundle)

    response = {
        "terminology_issues": term_result.get("terminology_issues", []),
        "syntax_errors": syntax_result.get("syntax_errors", []),
    }
    if ref:
        response["fhir_bundle_ref"] = ref
    else:
        response["fhir_bundle"] = fhir_bundle

    return response


@app.post("/api/v1/generate-bundle-async")
async def generate_bundle_async(request: Request, background_tasks: BackgroundTasks):
    """Async version: accept immediately, run generation in background, POST callback."""
    data = await request.json()
    callback_url = data.pop("callback_url", "")
    process_instance_id = data.pop("process_instance_id", "")
    background_tasks.add_task(_run_generate_background, data, callback_url, process_instance_id)
    return {"status": "accepted"}


def _run_generate_background(data: dict, callback_url: str, process_instance_id: str):
    try:
        planning_brief = resolve_ref(data, "planning_brief", _phi_store)
        state = {
            "planning_brief": planning_brief,
            "patient_demographics": data.get("patient_demographics", {}),
            "fhir_review_feedback": data.get("fhir_review_feedback", ""),
            "litellm_url": LITELLM_URL,
            "llm_model": LLM_MODEL,
            "llm_api_key": LLM_API_KEY,
        }

        gen_result = fhir_bundle_generator(state)
        state.update(gen_result)
        term_result = terminology_validator(state)
        syntax_result = fhir_syntax_validator(state)

        fhir_bundle = state.get("fhir_bundle", {})
        _, ref = store_artifact(_phi_store, f"{uuid4()}/fhir_bundle.json", fhir_bundle)

        result = {
            "terminology_issues": term_result.get("terminology_issues", []),
            "syntax_errors": syntax_result.get("syntax_errors", []),
        }
        if ref:
            result["fhir_bundle_ref"] = ref
        elif _phi_store:
            raise RuntimeError("Artifact store available but failed to store FHIR bundle")
        else:
            result["fhir_bundle"] = fhir_bundle
    except Exception as e:
        logger.error("Generate-bundle background task failed: %s", e)
        result = {"error": str(e), "terminology_issues": [], "syntax_errors": []}

    post_callback(callback_url, process_instance_id, "generate-done", result)
