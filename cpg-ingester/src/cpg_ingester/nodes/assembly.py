"""Assembly Agent — deterministic cross-reference resolution and integrity checks."""

import json
import logging
from pathlib import Path

import mlflow

from cpg_contracts import CONTRACT_VERSION
from cpg_ingester.output import write_artifact

logger = logging.getLogger(__name__)


def _resolve_cross_references(recommendations: list[dict], dmn_results: list[dict]) -> list[dict]:
    """Resolve cross-references and remove any pointing to missing items."""
    all_ids = set()
    for rec in recommendations:
        if rec.get("id"):
            all_ids.add(rec["id"])
    for dmn in dmn_results:
        summary = dmn.get("decision_model_summary", {})
        if summary.get("id"):
            all_ids.add(summary["id"])

    for rec in recommendations:
        refs = rec.get("cross_references", []) or []
        resolved = []
        for ref in refs:
            if isinstance(ref, dict):
                target = ref.get("target_id", "")
                if target in all_ids:
                    resolved.append(ref)
                else:
                    logger.warning("Removed cross-ref to missing target %s from rec %s", target[:8], rec.get("id", "?")[:8])
            elif isinstance(ref, str):
                if ref in all_ids:
                    resolved.append({"target_id": ref, "relationship": "related"})
                else:
                    logger.warning("Removed cross-ref to missing target %s from rec %s", ref[:8], rec.get("id", "?")[:8])
        rec["cross_references"] = resolved if resolved else None

    return recommendations


def _check_integrity(recommendations: list[dict], dmn_results: list[dict], cpg_metadata: dict) -> list[str]:
    """Run integrity checks on assembled output."""
    errors = []
    cpg_id = cpg_metadata.get("cpg_id", "")

    rec_ids = [r.get("id") for r in recommendations]
    if len(rec_ids) != len(set(rec_ids)):
        errors.append("Duplicate recommendation IDs found")

    dmn_ids = [d.get("decision_model_summary", {}).get("id") for d in dmn_results]
    if len(dmn_ids) != len(set(dmn_ids)):
        errors.append("Duplicate decision model IDs found")

    for rec in recommendations:
        if rec.get("source_cpg") and rec["source_cpg"] not in ("TBD", cpg_id):
            errors.append(f"Rec {rec.get('id', '?')[:8]}: source_cpg '{rec['source_cpg']}' doesn't match '{cpg_id}'")

    if not recommendations and not dmn_results:
        errors.append("No recommendations or decision models produced")

    return errors


def _collect_from_output_dir(output_dir: str) -> tuple[list[dict], list[dict]]:
    """Collect DMN and recommendation results from the output directory."""
    out = Path(output_dir)
    dmn_results = []
    for dmn_file in sorted(out.glob("dmn/*.dmn")):
        dmn_results.append({
            "dmn_xml": dmn_file.read_text(),
            "item": {"name": dmn_file.stem},
        })

    all_recs = []
    for rec_file in sorted(out.glob("recommendations-*.json")):
        try:
            data = json.loads(rec_file.read_text())
            if isinstance(data, list):
                all_recs.extend(data)
            elif isinstance(data, dict) and "recommendations" in data:
                all_recs.extend(data["recommendations"])
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse %s", rec_file)

    return dmn_results, all_recs


@mlflow.trace(name="assembly")
def assembly(state: dict) -> dict:
    """Assemble all validated outputs from DMN and Rec tracks."""
    logger.info("── Assembly ──")
    cpg_metadata = state.get("cpg_metadata", {})
    item_manifest = state.get("item_manifest", [])
    output_dir = state.get("output_dir", "output")

    dmn_results = state.get("dmn_results") or []
    all_recs = state.get("recommendation_results") or []
    if not dmn_results and not all_recs:
        dmn_results, all_recs = _collect_from_output_dir(output_dir)

    cpg_id = cpg_metadata.get("cpg_id", "UNKNOWN")
    for rec in all_recs:
        if not rec.get("source_cpg") or rec["source_cpg"] == "TBD":
            rec["source_cpg"] = cpg_id

    all_recs = _resolve_cross_references(all_recs, dmn_results)

    escalated = []
    for item in item_manifest:
        if item.get("escalated"):
            escalated.append(item)

    integrity_errors = _check_integrity(all_recs, dmn_results, cpg_metadata)
    if integrity_errors:
        for err in integrity_errors:
            logger.warning("Integrity check: %s", err)

    recommendation_bundle = {
        "contract_version": CONTRACT_VERSION,
        "source_cpg": cpg_id,
        "recommendations": all_recs,
    }

    assembly_report = {
        "cpg_id": cpg_id,
        "recommendations_count": len(all_recs),
        "dmn_models_count": len(dmn_results),
        "escalated_count": len(escalated),
        "integrity_errors": integrity_errors,
    }

    write_artifact(output_dir, "recommendation-bundle.json", recommendation_bundle)
    write_artifact(output_dir, "assembly-report.json", assembly_report)
    if escalated:
        write_artifact(output_dir, "escalated-items.json", escalated)

    logger.info(
        "Assembly complete: %d recs, %d DMN models, %d escalated, %d integrity errors",
        len(all_recs), len(dmn_results), len(escalated), len(integrity_errors),
    )

    return {
        "dmn_results": dmn_results,
        "recommendation_results": all_recs,
        "escalated_items": escalated,
        "assembly_report": assembly_report,
    }
