"""Decision Engine pod service — DMN Executor proxy to Kogito.

Also handles DMN model management (deploy, list) since the model
registry lives in this pod's process.
Consumes: ips_bundle_ref (fetches patient bundle from artifact store).

Security profile: Kogito runtime access only.
"""

import logging

from fastapi import FastAPI, HTTPException, Request

from cpg_contracts import get_phi_store, resolve_ref
from acp_writer.api import _dynamic_models, _parse_dmn_metadata
from acp_writer.nodes.dmn_executor import dmn_executor

logger = logging.getLogger(__name__)

app = FastAPI(title="acp-writer-decision-engine", version="0.1.0")
_phi_store = get_phi_store()


@app.get("/health")
def health():
    return {"status": "UP", "service": "decision-engine"}


# --- DMN model management (used by cpg-ingester Delivery) ---


@app.post("/api/v1/decisions/models", status_code=201)
async def deploy_decision_model(request: Request):
    body = await request.body()
    dmn_xml = body.decode("utf-8")
    summary = _parse_dmn_metadata(dmn_xml)
    _dynamic_models[summary.id] = {"summary": summary, "dmn_xml": dmn_xml}
    return summary.model_dump(mode="json")


@app.get("/api/v1/decisions/models")
def list_decision_models():
    return [m["summary"].model_dump(mode="json") for m in _dynamic_models.values()]


# --- Pipeline execution ---


@app.post("/api/v1/execute")
async def execute(request: Request):
    """Execute DMN models against patient data."""
    data = await request.json()
    ips_bundle = resolve_ref(data, "ips_bundle", _phi_store)
    state = {
        "ips_bundle": ips_bundle,
        "applicable_dmn_models": data.get("applicable_dmn_models", []),
        "dmn_dependency_graph": data.get("dmn_dependency_graph", []),
    }
    result = dmn_executor(state)
    return {"dmn_results": result.get("dmn_results", [])}
