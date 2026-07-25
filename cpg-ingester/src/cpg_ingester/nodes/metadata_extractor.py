"""Metadata Extractor — extracts CPGMetadata with validation."""

import json
import logging
import re
import time

import mlflow
from cpg_contracts import CPGMetadata, GradingSystem
from cpg_contracts import get_llm
from cpg_ingester.nodes.structure_analyzer import _parse_llm_json
from cpg_ingester.output import write_artifact
from cpg_ingester.prompts.metadata_extractor import (
    METADATA_EXTRACTOR_SYSTEM,
    METADATA_EXTRACTOR_USER,
)

logger = logging.getLogger(__name__)

GRADING_VOCABULARY = {
    "GRADE": [
        "strong recommendation", "conditional recommendation",
        "high certainty", "moderate certainty", "low certainty", "very low certainty",
        "high quality", "moderate quality", "low quality", "very low quality",
        "strong for", "conditional for", "strong against", "conditional against",
    ],
    "COR-LOE": [
        "class i", "class ii", "class iia", "class iib", "class iii",
        "level a", "level b", "level c", "level b-r", "level b-nr",
        "level c-ld", "level c-eo",
    ],
}


def _cross_check_grading_system(declared: str | None, markdown: str) -> str | None:
    """Cross-check declared grading system against vocabulary found in the document."""
    if not declared:
        return None

    text_lower = markdown.lower()

    for system, vocab in GRADING_VOCABULARY.items():
        matches = sum(1 for term in vocab if term in text_lower)
        if system == declared and matches == 0:
            return f"Declared grading system '{declared}' but no matching vocabulary found in document"
        if system != declared and matches >= 3:
            return f"Declared '{declared}' but document contains {matches} terms matching '{system}'"

    return None


@mlflow.trace(name="metadata_extractor")
def metadata_extractor(state: dict) -> dict:
    """Extract CPGMetadata from the document."""
    logger.info("── Metadata Extractor ──")
    markdown = state.get("markdown", "")
    output_dir = state.get("output_dir", "output")

    llm = get_llm(state)

    content = markdown[:6000]

    logger.info("Calling LLM...")
    t0 = time.time()
    response = llm.invoke([
        {"role": "system", "content": METADATA_EXTRACTOR_SYSTEM},
        {"role": "user", "content": METADATA_EXTRACTOR_USER.format(content=content)},
    ])

    logger.info("LLM responded in %.1fs", time.time() - t0)

    try:
        raw = _parse_llm_json(response.content)
    except (json.JSONDecodeError, ValueError):
        logger.error("Failed to parse metadata extractor response")
        return {"cpg_metadata": {}}

    grading_str = raw.get("grading_system")
    grading_enum = None
    if grading_str:
        try:
            grading_enum = GradingSystem(grading_str)
        except ValueError:
            logger.warning("Invalid grading_system value: %s", grading_str)

    try:
        metadata = CPGMetadata(
            cpg_id=raw.get("cpg_id") or "UNKNOWN",
            title=raw.get("title") or "Untitled",
            version=raw.get("version"),
            publication_date=raw.get("publication_date"),
            evidence_review_date=raw.get("evidence_review_date"),
            issuing_body=raw.get("issuing_body"),
            grading_system=grading_enum,
            scope=raw.get("scope"),
            supersedes=raw.get("supersedes"),
        )
    except Exception as e:
        logger.error("CPGMetadata validation failed: %s", e)
        return {"cpg_metadata": raw}

    grading_warning = _cross_check_grading_system(grading_str, markdown)
    if grading_warning:
        logger.warning("Grading system cross-check: %s", grading_warning)

    metadata_dict = metadata.model_dump(mode="json")
    write_artifact(output_dir, "metadata.json", metadata_dict)

    logger.info(
        "Extracted metadata: cpg_id=%s, title=%s, grading=%s",
        metadata.cpg_id, metadata.title[:50], metadata.grading_system,
    )

    return {"cpg_metadata": metadata_dict}
