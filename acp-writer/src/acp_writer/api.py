"""FastAPI REST API for the acp-writer service."""

import base64
import json
import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import mlflow
import requests
from fastapi import FastAPI, HTTPException, Request, Response

from cpg_contracts import (
    CPGMetadata,
    DecisionModelSummary,
    DecisionVariable,
    Recommendation,
    RecommendationBundle,
    RecommendationSearchRequest,
)

from acp_writer.store.embedding import EmbeddingProvider, FakeEmbeddingProvider
from acp_writer.store.guidelines_store import GuidelinesStore
from acp_writer.store.vector_store import InMemoryVectorStore, VectorStore

try:
    mlflow.fastapi.autolog()
except AttributeError:
    pass

logger = logging.getLogger(__name__)

KOGITO_URL = os.environ.get("KOGITO_URL", "http://localhost:8081")
DMN_NS = "https://www.omg.org/spec/DMN/20191111/MODEL/"

_dynamic_models: dict[str, dict] = {}

# --- Store initialization ---
# Use FakeEmbeddingProvider by default to avoid downloading a model on import.
# Set EMBEDDING_MODEL env var or call init_stores() with a real provider.

_embedding_provider: EmbeddingProvider = FakeEmbeddingProvider(dimensions=8)
_vector_store: VectorStore = InMemoryVectorStore(_embedding_provider)
_guidelines_store: GuidelinesStore = GuidelinesStore(_vector_store)


def init_stores(embedding_provider: EmbeddingProvider | None = None) -> None:
    """Re-initialize stores with a specific embedding provider."""
    global _embedding_provider, _vector_store, _guidelines_store
    if embedding_provider:
        _embedding_provider = embedding_provider
    _vector_store = InMemoryVectorStore(_embedding_provider)
    _guidelines_store = GuidelinesStore(_vector_store)


app = FastAPI(
    title="ACP Writer API",
    version="0.2.0",
    description="Composes patient-specific, FHIR-compliant care plans.",
)

from acp_writer.ui.app import app as ui_app, _setup_sample_data
app.mount("/ui", ui_app)


@app.on_event("startup")
async def startup():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    _setup_sample_data()


def _check_kogito() -> bool:
    try:
        r = requests.get(f"{KOGITO_URL}/q/health/ready", timeout=5)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _parse_dmn_metadata(dmn_xml: str) -> DecisionModelSummary:
    """Extract model name, inputs, and outputs from DMN XML."""
    root = ET.fromstring(dmn_xml)

    model_name = root.get("name", "unknown")
    model_id = model_name.lower().replace(" ", "-")

    inputs = []
    for input_data in root.findall(f"{{{DMN_NS}}}inputData"):
        var = input_data.find(f"{{{DMN_NS}}}variable")
        if var is not None:
            inputs.append(DecisionVariable(
                name=var.get("name", ""),
                type=var.get("typeRef", "string"),
            ))

    outputs = []
    for decision in root.findall(f"{{{DMN_NS}}}decision"):
        dt = decision.find(f"{{{DMN_NS}}}decisionTable")
        if dt is not None:
            for output in dt.findall(f"{{{DMN_NS}}}output"):
                outputs.append(DecisionVariable(
                    name=output.get("name", ""),
                    type=output.get("typeRef", "string"),
                ))

    return DecisionModelSummary(
        id=model_id,
        name=model_name,
        inputs=inputs,
        outputs=outputs,
        deployed_at=datetime.now(timezone.utc),
    )


@mlflow.trace(span_type="TOOL", name="evaluate_jit_dmn")
def _evaluate_jit(dmn_xml: str, inputs: dict) -> dict:
    """Evaluate DMN via the JIT endpoint on the decision-service."""
    dmn_b64 = base64.b64encode(dmn_xml.encode()).decode()
    r = requests.post(
        f"{KOGITO_URL}/jit/dmn",
        json={"dmn_xml_base64": dmn_b64, "inputs": inputs},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# --- Health ---


@app.get("/health")
def health():
    return {"status": "UP"}


@app.get("/health/ready")
def readiness():
    if _check_kogito():
        return {"status": "UP"}
    raise HTTPException(status_code=503, detail="Decision engine not available")


@app.get("/api/v1/status")
def status():
    kogito_healthy = _check_kogito()
    total_models = len(_dynamic_models)
    return {
        "version": "0.2.0",
        "decision_engine": {
            "status": "healthy" if kogito_healthy else "unavailable",
            "models_deployed": total_models,
        },
        "knowledge_base": {
            "status": "available",
            "guidelines_registered": _guidelines_store.count(),
            "recommendations_ingested": _vector_store.count(),
        },
    }


# --- Care Plans ---


@app.post("/api/v1/careplans", status_code=201)
async def generate_careplan(request: Request):
    bundle = await request.json()

    if bundle.get("resourceType") != "Bundle":
        raise HTTPException(status_code=400, detail="Request body must be a FHIR Bundle")

    import uuid

    from acp_writer.checkpointer import get_checkpointer
    from acp_writer.pipeline import build_pipeline

    litellm_url = os.environ.get("LITELLM_URL", "http://localhost:4000")
    llm_model = os.environ.get("LLM_MODEL", "default")
    llm_api_key = os.environ.get("LLM_API_KEY", "sk-change-me")

    run_id = str(uuid.uuid4())
    graph = build_pipeline()
    checkpointer = get_checkpointer()
    compiled = graph.compile(checkpointer=checkpointer)

    try:
        result = compiled.invoke(
            {
                "ips_bundle": bundle,
                "run_id": run_id,
                "litellm_url": litellm_url,
                "llm_model": llm_model,
                "llm_api_key": llm_api_key,
            },
            config={"configurable": {"thread_id": run_id}},
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Care plan generation failed: {e}")

    fhir_bundle = result.get("fhir_bundle", {})
    return Response(
        content=json.dumps(fhir_bundle),
        media_type="application/fhir+json",
        status_code=201,
    )


@app.get("/api/v1/careplans")
def list_careplans(patient: str | None = None, status: str | None = None):
    from acp_writer.nodes.fhir_server_writer import list_care_plans
    return list_care_plans(patient=patient, status=status)


@app.get("/api/v1/careplans/{careplan_id}")
def get_careplan(careplan_id: str):
    from acp_writer.nodes.fhir_server_writer import get_care_plan
    cp = get_care_plan(careplan_id)
    if not cp:
        raise HTTPException(status_code=404, detail=f"Care plan '{careplan_id}' not found")
    return cp


@app.put("/api/v1/careplans/{careplan_id}/status")
async def update_careplan_status(careplan_id: str, request: Request):
    from acp_writer.nodes.fhir_server_writer import approve_care_plan, reject_care_plan
    data = await request.json()
    new_status = data.get("status")
    if new_status == "active":
        result = approve_care_plan(careplan_id, clinician=data.get("clinician"))
        if not result:
            raise HTTPException(status_code=404, detail=f"Care plan '{careplan_id}' not found")
        return result
    elif new_status == "entered-in-error":
        reason = data.get("reason", "No reason provided")
        result = reject_care_plan(careplan_id, reason=reason)
        if not result:
            raise HTTPException(status_code=404, detail=f"Care plan '{careplan_id}' not found")
        return result
    else:
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}. Use 'active' or 'entered-in-error'.")


# --- Decision Models ---


@app.post("/api/v1/decisions/models", status_code=201)
async def deploy_decision_model(request: Request):
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    dmn_xml = body.decode("utf-8")

    try:
        summary = _parse_dmn_metadata(dmn_xml)
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid DMN XML: {e}")

    _dynamic_models[summary.id] = {
        "summary": summary,
        "dmn_xml": dmn_xml,
    }

    logger.info("Deployed decision model: %s (%s)", summary.name, summary.id)
    return summary.model_dump(mode="json")


@app.get("/api/v1/decisions/models")
def list_decision_models():
    return [m["summary"].model_dump(mode="json") for m in _dynamic_models.values()]


@app.get("/api/v1/decisions/models/{model_id}")
def get_decision_model(model_id: str):
    model = _dynamic_models.get(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    result = model["summary"].model_dump(mode="json")
    result["dmn_xml"] = model["dmn_xml"]
    return result


@app.delete("/api/v1/decisions/models/{model_id}", status_code=204)
def remove_decision_model(model_id: str):
    if model_id not in _dynamic_models:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    del _dynamic_models[model_id]
    logger.info("Removed decision model: %s", model_id)


@app.post("/api/v1/decisions/evaluate/{model_id}")
async def evaluate_decision(model_id: str, request: Request):
    model = _dynamic_models.get(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    inputs = await request.json()
    try:
        result = _evaluate_jit(model["dmn_xml"], inputs)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Decision evaluation failed: {e}")


# --- Guidelines ---


@app.post("/api/v1/guidelines", status_code=201)
async def register_guideline(request: Request):
    data = await request.json()
    try:
        metadata = CPGMetadata.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid CPG metadata: {e}")
    result = _guidelines_store.register(metadata)
    return result.model_dump(mode="json")


@app.get("/api/v1/guidelines")
def list_guidelines():
    return [g.model_dump(mode="json") for g in _guidelines_store.list_all()]


@app.get("/api/v1/guidelines/{cpg_id}")
def get_guideline(cpg_id: str):
    g = _guidelines_store.get(cpg_id)
    if not g:
        raise HTTPException(status_code=404, detail=f"Guideline '{cpg_id}' not found")
    return g.model_dump(mode="json")


@app.delete("/api/v1/guidelines/{cpg_id}", status_code=204)
def delete_guideline(cpg_id: str):
    if not _guidelines_store.delete(cpg_id):
        raise HTTPException(status_code=404, detail=f"Guideline '{cpg_id}' not found")


# --- Knowledge / Recommendations ---


@app.post("/api/v1/knowledge/recommendations", status_code=201)
async def ingest_recommendation(request: Request):
    data = await request.json()
    try:
        rec = Recommendation.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid recommendation: {e}")
    _vector_store.add(rec)
    return {"id": rec.id, "status": "ingested"}


@app.post("/api/v1/knowledge/recommendations/batch", status_code=201)
async def ingest_recommendation_batch(request: Request):
    data = await request.json()
    try:
        bundle = RecommendationBundle.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid recommendation bundle: {e}")
    _vector_store.add_batch(bundle.recommendations)
    return {
        "source_cpg": bundle.source_cpg,
        "count": len(bundle.recommendations),
        "status": "ingested",
    }


@app.get("/api/v1/knowledge/recommendations")
def list_recommendations(source_cpg: str | None = None):
    recs = _vector_store.list_all(source_cpg=source_cpg)
    return [r.model_dump(mode="json") for r in recs]


@app.get("/api/v1/knowledge/recommendations/{recommendation_id}")
def get_recommendation(recommendation_id: str):
    rec = _vector_store.get(recommendation_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Recommendation '{recommendation_id}' not found")
    return rec.model_dump(mode="json")


@app.post("/api/v1/knowledge/search")
async def search_knowledge(request: Request):
    data = await request.json()
    try:
        search_req = RecommendationSearchRequest.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid search request: {e}")
    result = _vector_store.search(search_req)
    return result.model_dump(mode="json")
