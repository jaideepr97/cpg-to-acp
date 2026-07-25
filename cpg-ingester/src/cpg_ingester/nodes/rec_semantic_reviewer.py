"""Recommendation Semantic Reviewer — LLM review of content faithfulness and certainty accuracy."""

import json
import logging
import time

import mlflow
from cpg_contracts import get_llm
from cpg_ingester.nodes.structure_analyzer import _parse_llm_json
from cpg_ingester.output import write_artifact
from cpg_ingester.prompts.rec_semantic_reviewer import (
    REC_SEMANTIC_REVIEWER_SYSTEM,
    REC_SEMANTIC_REVIEWER_USER,
)

logger = logging.getLogger(__name__)


@mlflow.trace(name="rec_semantic_reviewer")
def rec_semantic_reviewer(state: dict) -> dict:
    """Review extracted recommendations against source material."""
    logger.info("── Rec Semantic Reviewer ──")
    recommendations = state.get("recommendations", [])
    source_pages = state.get("source_pages", "")
    output_dir = state.get("output_dir", "output")
    review_count = state.get("review_count", 0)
    items = state.get("items", [])

    if not recommendations:
        return {"semantic_discrepancies": ["No recommendations to review"]}

    if not source_pages:
        logger.warning("No source pages for semantic review — skipping")
        return {"semantic_discrepancies": []}

    llm = get_llm(state)

    recs_str = json.dumps(recommendations, indent=2, default=str)

    logger.info("Calling LLM...")
    t0 = time.time()
    response = llm.invoke([
        {"role": "system", "content": REC_SEMANTIC_REVIEWER_SYSTEM},
        {"role": "user", "content": REC_SEMANTIC_REVIEWER_USER.format(
            recommendations=recs_str,
            source_pages=source_pages,
        )},
    ])
    logger.info("LLM responded in %.1fs", time.time() - t0)

    try:
        result = _parse_llm_json(response.content)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse semantic review response")
        return {"semantic_discrepancies": []}

    discrepancies_found = result.get("discrepancies_found", False)
    discrepancies = result.get("discrepancies", [])
    checks = result.get("checks", [])
    missing = result.get("missing_recommendations", [])

    passed = sum(1 for c in checks if not c.get("issues"))
    failed = sum(1 for c in checks if c.get("issues"))

    section = items[0].get("section", "unknown") if items else "unknown"
    review_report = {
        "section": section,
        "review_iteration": review_count + 1,
        "recommendations_checked": len(checks),
        "passed": passed,
        "with_issues": failed,
        "missing_recommendations": missing,
        "checks": checks,
        "summary": result.get("summary", ""),
    }
    write_artifact(output_dir, f"rec-review-{section}-{review_count + 1}.json", review_report)

    if discrepancies_found:
        logger.warning(
            "Rec semantic review for section %s: %d/%d recs have issues, %d missing",
            section, failed, len(checks), len(missing),
        )
        for d in discrepancies:
            logger.warning("  %s", d)
    else:
        logger.info(
            "Rec semantic review passed for section %s: %d/%d recs OK",
            section, passed, len(checks),
        )

    return {"semantic_discrepancies": discrepancies if discrepancies_found else []}
