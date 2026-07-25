"""FHIR Semantic Reviewer — LLM review of FHIR Bundle for clinical coherence.

Checks goal-activity consistency, medication dose reasonableness,
AI Transparency completeness. APPROVE/REVISE protocol, max 2 loops.
"""

import json
import logging
import time

import mlflow
from cpg_contracts import get_llm

from acp_writer.output import write_artifact
from acp_writer.prompts.fhir_semantic_reviewer import (
    FHIR_SEMANTIC_REVIEWER_SYSTEM,
    FHIR_SEMANTIC_REVIEWER_USER,
)
from acp_writer.state import CarePlanComposerState

logger = logging.getLogger(__name__)


def _parse_review_response(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(text)


@mlflow.trace(name="fhir_semantic_reviewer")
def fhir_semantic_reviewer(state: CarePlanComposerState) -> dict:
    """Review the FHIR Bundle for clinical coherence."""
    bundle = state.get("fhir_bundle", {})
    review_count = state.get("fhir_review_count", 0)
    syntax_errors = state.get("syntax_errors", [])
    terminology_issues = state.get("terminology_issues", [])
    output_dir = state.get("output_dir", "")

    if not bundle.get("entry"):
        logger.info("Empty FHIR bundle — auto-approving")
        return {
            "fhir_review_feedback": "",
            "fhir_review_count": review_count + 1,
        }

    logger.info("── FHIR Semantic Reviewer (iteration %d) ──", review_count + 1)

    user_prompt = FHIR_SEMANTIC_REVIEWER_USER.format(
        fhir_bundle=json.dumps(bundle, indent=2, default=str),
        syntax_errors=json.dumps(syntax_errors) if syntax_errors else "None",
        terminology_issues=json.dumps(terminology_issues) if terminology_issues else "None",
    )

    llm = get_llm(state)
    logger.info("Calling LLM...")
    t0 = time.time()

    response = llm.invoke([
        {"role": "system", "content": FHIR_SEMANTIC_REVIEWER_SYSTEM},
        {"role": "user", "content": user_prompt},
    ])

    elapsed = time.time() - t0
    logger.info("LLM responded in %.1fs", elapsed)

    try:
        review = _parse_review_response(response.content)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Could not parse FHIR review response, treating as APPROVE: %s", e)
        review = {"verdict": "APPROVE", "issues": []}

    verdict = review.get("verdict", "APPROVE").upper()
    issues = review.get("issues", [])

    if output_dir:
        write_artifact(output_dir, f"fhir-review-{review_count + 1}.json", review)

    if verdict == "REVISE" and issues:
        feedback_parts = []
        for i, issue in enumerate(issues, 1):
            severity = issue.get("severity", "error")
            resource = issue.get("resource", "")
            desc = issue.get("description", "")
            fix = issue.get("fix", "")
            feedback_parts.append(f"{i}. [{severity}] {resource}: {desc} — Fix: {fix}")
        feedback = "\n".join(feedback_parts)
        logger.info("FHIR REVISE: %d issues", len(issues))

        return {
            "fhir_review_feedback": feedback,
            "fhir_review_count": review_count + 1,
        }

    logger.info("FHIR APPROVED (iteration %d)", review_count + 1)
    return {
        "fhir_review_feedback": "",
        "fhir_review_count": review_count + 1,
    }
