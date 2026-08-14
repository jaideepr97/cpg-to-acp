"""Delivery Agent — publishes assembled artifacts to the artifact store.

The ingester does not communicate with downstream consumers directly.
It publishes artifacts to a well-known location in MinIO/S3 and returns
a manifest.  The SonataFlow orchestrator owns downstream notification.
"""

import logging

import mlflow

from cpg_ingester.output import write_artifact

logger = logging.getLogger(__name__)


@mlflow.trace(name="delivery")
def delivery(state: dict) -> dict:
    """Publish assembled artifacts to the artifact store."""
    logger.info("── Delivery ──")
    cpg_metadata = state.get("cpg_metadata", {})
    dmn_results = state.get("dmn_results", []) or []
    recommendation_results = state.get("recommendation_results", [])
    escalated_items = state.get("escalated_items", [])
    assembly_report = state.get("assembly_report", {})
    output_dir = state.get("output_dir", "output")
    store = state.get("artifact_store")

    cpg_id = cpg_metadata.get("cpg_id", "UNKNOWN")
    artifacts: list[dict] = []
    errors: list[str] = []

    if not store:
        logger.info("No artifact store available — writing to output_dir only")
        status = {
            "published": False,
            "reason": "no artifact store configured",
            "cpg_id": cpg_id,
            "artifacts": [],
            "errors": [],
        }
        write_artifact(output_dir, "delivery-status.json", status)
        return {"delivery_status": status}

    base_key = f"published/{cpg_id}"

    if cpg_metadata:
        try:
            ref = store.put(f"{base_key}/metadata.json", cpg_metadata)
            artifacts.append({"type": "metadata", "ref": ref, "cpg_id": cpg_id})
            logger.info("Published metadata: %s", ref)
        except Exception as e:
            errors.append(f"Failed to publish metadata: {e}")
            logger.error("Failed to publish metadata: %s", e)

    for dmn in dmn_results:
        dmn_xml = dmn.get("dmn_xml", "") if isinstance(dmn, dict) else ""
        if not dmn_xml:
            continue
        name = dmn.get("item", {}).get("name", "unknown") if isinstance(dmn, dict) else "unknown"
        try:
            ref = store.put_raw(
                f"{base_key}/dmn/{name}.dmn",
                dmn_xml.encode("utf-8"),
                "application/xml",
            )
            artifacts.append({"type": "dmn", "ref": ref, "name": name})
            logger.info("Published DMN model: %s", ref)
        except Exception as e:
            errors.append(f"Failed to publish DMN '{name}': {e}")
            logger.error("Failed to publish DMN '%s': %s", name, e)

    if recommendation_results:
        bundle = {
            "contract_version": cpg_metadata.get("contract_version", "1.0"),
            "source_cpg": cpg_id,
            "recommendations": recommendation_results if isinstance(recommendation_results, list) else [],
        }
        try:
            ref = store.put(f"{base_key}/recommendations.json", bundle)
            artifacts.append({"type": "recommendations", "ref": ref, "count": len(bundle["recommendations"])})
            logger.info("Published %d recommendations: %s", len(bundle["recommendations"]), ref)
        except Exception as e:
            errors.append(f"Failed to publish recommendations: {e}")
            logger.error("Failed to publish recommendations: %s", e)

    if assembly_report:
        try:
            ref = store.put(f"{base_key}/assembly-report.json", assembly_report)
            artifacts.append({"type": "assembly_report", "ref": ref})
        except Exception as e:
            errors.append(f"Failed to publish assembly report: {e}")

    if escalated_items:
        try:
            ref = store.put(f"{base_key}/escalated-items.json", escalated_items)
            artifacts.append({"type": "escalated_items", "ref": ref, "count": len(escalated_items)})
        except Exception as e:
            errors.append(f"Failed to publish escalated items: {e}")

    status = {
        "published": len(artifacts) > 0 and len(errors) == 0,
        "cpg_id": cpg_id,
        "artifact_location": f"{store.bucket}:{base_key}",
        "artifacts": artifacts,
        "errors": errors,
        "escalated_items_count": len(escalated_items),
    }
    write_artifact(output_dir, "delivery-status.json", status)

    if errors:
        logger.error("Delivery completed with %d errors", len(errors))
    else:
        logger.info("Delivery complete — %d artifacts published to %s", len(artifacts), status["artifact_location"])

    return {"delivery_status": status}
