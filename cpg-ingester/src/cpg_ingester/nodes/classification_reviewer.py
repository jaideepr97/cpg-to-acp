"""Classification Reviewer — adversarial review of Item Identifier output."""

import json
import logging
import time

import mlflow
from cpg_contracts import get_llm
from cpg_ingester.nodes.structure_analyzer import _parse_llm_json
from cpg_ingester.output import write_artifact
from cpg_ingester.prompts.classification_reviewer import (
    CLASSIFICATION_REVIEWER_SYSTEM,
    CLASSIFICATION_REVIEWER_USER,
)

logger = logging.getLogger(__name__)


@mlflow.trace(name="classification_reviewer")
def classification_reviewer(state: dict) -> dict:
    """Adversarial review of the item manifest."""
    logger.info("── Classification Reviewer (iteration %d) ──", state.get("classification_review_count", 0) + 1)
    manifest = state.get("item_manifest", [])
    section_map = state.get("section_map", [])
    markdown = state.get("markdown", "")
    grading_definitions = state.get("grading_definitions", "")
    output_dir = state.get("output_dir", "output")
    review_count = state.get("classification_review_count", 0)

    if not manifest:
        logger.warning("Empty manifest — nothing to review")
        return {"classification_review_feedback": ""}

    llm = get_llm(state)

    section_map_str = "\n".join(
        f"- [{s['classification']}] Page {s.get('page_start', '?')}: \"{s['heading']}\""
        for s in section_map
    )

    manifest_str = json.dumps(manifest, indent=2, default=str)

    content = markdown[:12000]

    logger.info("Calling LLM...")
    t0 = time.time()
    response = llm.invoke([
        {"role": "system", "content": CLASSIFICATION_REVIEWER_SYSTEM},
        {"role": "user", "content": CLASSIFICATION_REVIEWER_USER.format(
            grading_system=grading_definitions or "(not specified)",
            section_map=section_map_str,
            manifest=manifest_str,
            content=content,
        )},
    ])

    logger.info("LLM responded in %.1fs", time.time() - t0)

    try:
        result = _parse_llm_json(response.content)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse reviewer response, treating as no issues")
        result = {"issues_found": False, "feedback": "", "issues": []}

    issues_found = result.get("issues_found", False)
    feedback = result.get("feedback", "")
    issues = result.get("issues", [])

    review_report = {
        "review_iteration": review_count + 1,
        "issues_found": issues_found,
        "issue_count": len(issues),
        "issues": issues,
        "feedback": feedback,
    }
    write_artifact(output_dir, f"classification-review-{review_count + 1}.json", review_report)

    if issues_found:
        logger.info(
            "Classification reviewer found %d issues (iteration %d)",
            len(issues), review_count + 1,
        )
        for issue in issues:
            logger.info(
                "  [%s] %s: %s",
                issue.get("issue_type", "?"),
                issue.get("item_name", "?"),
                issue.get("description", "?"),
            )
    else:
        logger.info("Classification reviewer approved manifest (iteration %d)", review_count + 1)

    return {
        "classification_review_feedback": feedback if issues_found else "",
    }
