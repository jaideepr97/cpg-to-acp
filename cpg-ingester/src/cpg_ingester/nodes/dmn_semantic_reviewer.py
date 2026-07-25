"""DMN Semantic Reviewer — adversarial LLM review using claim-level decomposition."""

import json
import logging
import time

import mlflow
from cpg_contracts import get_llm
from cpg_ingester.nodes.structure_analyzer import _parse_llm_json
from cpg_ingester.output import write_artifact
from cpg_ingester.prompts.dmn_semantic_reviewer import (
    DMN_SEMANTIC_REVIEWER_SYSTEM,
    DMN_SEMANTIC_REVIEWER_USER,
)

logger = logging.getLogger(__name__)


@mlflow.trace(name="dmn_semantic_reviewer")
def dmn_semantic_reviewer(state: dict) -> dict:
    """Adversarial review of generated DMN against source material."""
    logger.info("── DMN Semantic Reviewer ──")
    dmn_xml = state.get("dmn_xml", "")
    item = state.get("item", {})
    source_pages = state.get("source_pages", "")
    output_dir = state.get("output_dir", "output")
    review_count = state.get("review_count", 0)

    name = item.get("name", "unknown")

    if not dmn_xml:
        return {"semantic_discrepancies": ["No DMN XML to review"]}

    if not source_pages:
        logger.warning("No source pages for semantic review of '%s' — skipping", name)
        return {"semantic_discrepancies": []}

    llm = get_llm(state)

    logger.info("Calling LLM...")
    t0 = time.time()
    response = llm.invoke([
        {"role": "system", "content": DMN_SEMANTIC_REVIEWER_SYSTEM},
        {"role": "user", "content": DMN_SEMANTIC_REVIEWER_USER.format(
            name=name,
            dmn_xml=dmn_xml,
            source_pages=source_pages,
        )},
    ])
    logger.info("LLM responded in %.1fs", time.time() - t0)

    try:
        result = _parse_llm_json(response.content)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse semantic review response for '%s'", name)
        return {"semantic_discrepancies": []}

    discrepancies_found = result.get("discrepancies_found", False)
    discrepancies = result.get("discrepancies", [])
    claims = result.get("claims_checked", [])

    verified = sum(1 for c in claims if c.get("verdict") == "VERIFIED")
    failed = sum(1 for c in claims if c.get("verdict") == "DISCREPANCY")

    safe_name = name.lower().replace(" ", "-").replace("/", "-")[:50]
    review_report = {
        "decision": name,
        "review_iteration": review_count + 1,
        "claims_checked": len(claims),
        "verified": verified,
        "discrepancies": failed,
        "claims": claims,
        "summary": result.get("summary", ""),
    }
    write_artifact(output_dir, f"dmn-review-{safe_name}-{review_count + 1}.json", review_report)

    if discrepancies_found:
        logger.warning(
            "DMN semantic review for '%s': %d/%d claims have discrepancies",
            name, failed, len(claims),
        )
        for d in discrepancies:
            logger.warning("  %s", d)
    else:
        logger.info(
            "DMN semantic review passed for '%s': %d/%d claims verified",
            name, verified, len(claims),
        )

    return {"semantic_discrepancies": discrepancies if discrepancies_found else []}
