"""Assembly pod service — deterministic cross-reference resolution and integrity checks.

Consumes: analysis_result_ref. Produces: assembly_result_ref.
Security profile: no external network, no LLM.
"""

import logging
import tempfile
from uuid import uuid4

from fastapi import FastAPI, Request

from cpg_contracts import get_artifact_store, resolve_ref, store_artifact
from cpg_ingester.nodes.assembly import assembly

logger = logging.getLogger(__name__)

app = FastAPI(title="cpg-ingester-assembly", version="0.1.0")
_store = get_artifact_store()


@app.get("/health")
def health():
    return {"status": "UP", "service": "assembly"}


@app.post("/api/v1/assemble")
async def assemble(request: Request):
    """Assemble validated outputs from DMN and Rec generation."""
    data = await request.json()

    analysis = resolve_ref(data, "analysis_result", _store)
    if isinstance(analysis, dict) and "dmn_results" in analysis:
        cpg_metadata = analysis.get("cpg_metadata", data.get("cpg_metadata", {}))
        item_manifest = analysis.get("item_manifest", data.get("item_manifest", []))
        dmn_results = analysis.get("dmn_results", [])
        recommendation_results = analysis.get("recommendation_results", [])
    else:
        cpg_metadata = data.get("cpg_metadata", {})
        item_manifest = data.get("item_manifest", [])
        dmn_results = data.get("dmn_results", [])
        recommendation_results = data.get("recommendation_results", [])

    with tempfile.TemporaryDirectory() as output_dir:
        state = {
            "cpg_metadata": cpg_metadata,
            "item_manifest": item_manifest,
            "dmn_results": dmn_results,
            "recommendation_results": recommendation_results,
            "output_dir": output_dir,
        }

        result = assembly(state)

        output = {
            "cpg_metadata": cpg_metadata,
            "dmn_results": result.get("dmn_results", []),
            "recommendation_results": result.get("recommendation_results", []),
            "escalated_items": result.get("escalated_items", []),
            "assembly_report": result.get("assembly_report", {}),
        }

        _, ref = store_artifact(_store, f"{uuid4()}/assembly_result.json", output)
        if ref:
            return {"assembly_result_ref": ref}
        return output
