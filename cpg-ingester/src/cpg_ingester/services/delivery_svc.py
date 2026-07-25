"""Delivery pod service — sends artifacts to acp-writer API.

Consumes: assembly_result_ref. Delivers via the acp-writer API gateway.
Security profile: acp-writer API access only.
"""

import logging
import os
import tempfile

from fastapi import FastAPI, Request

from cpg_contracts import get_artifact_store, resolve_ref
from cpg_ingester.nodes.delivery import delivery

logger = logging.getLogger(__name__)

app = FastAPI(title="cpg-ingester-delivery", version="0.1.0")
_store = get_artifact_store()

ACP_WRITER_URL = os.environ.get("ACP_WRITER_URL", "")


@app.get("/health")
def health():
    return {"status": "UP", "service": "delivery"}


@app.post("/api/v1/deliver")
async def deliver(request: Request):
    """Deliver assembled artifacts to acp-writer."""
    data = await request.json()

    assembly_result = resolve_ref(data, "assembly_result", _store)
    if isinstance(assembly_result, dict) and "dmn_results" in assembly_result:
        cpg_metadata = assembly_result.get("cpg_metadata", data.get("cpg_metadata", {}))
        dmn_results = assembly_result.get("dmn_results", [])
        recommendation_results = assembly_result.get("recommendation_results", [])
        escalated_items = assembly_result.get("escalated_items", [])
        assembly_report = assembly_result.get("assembly_report", {})
    else:
        cpg_metadata = data.get("cpg_metadata", {})
        dmn_results = data.get("dmn_results", [])
        recommendation_results = data.get("recommendation_results", [])
        escalated_items = data.get("escalated_items", [])
        assembly_report = data.get("assembly_report", {})

    with tempfile.TemporaryDirectory() as output_dir:
        state = {
            "cpg_metadata": cpg_metadata,
            "dmn_results": dmn_results,
            "recommendation_results": recommendation_results,
            "escalated_items": escalated_items,
            "assembly_report": assembly_report,
            "acp_writer_url": data.get("acp_writer_url") or ACP_WRITER_URL,
            "output_dir": output_dir,
        }

        result = delivery(state)

        return {
            "delivery_status": result.get("delivery_status", {}),
        }
