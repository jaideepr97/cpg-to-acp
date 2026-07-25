"""DMN Creator — generates DMN 1.4 XML per decision item."""

import logging
import time

import mlflow
from cpg_contracts import get_llm
from cpg_ingester.output import write_artifact
from cpg_ingester.prompts.dmn_creator import DMN_CREATOR_SYSTEM, DMN_CREATOR_USER
from cpg_ingester.reference.dmn_examples import REFERENCE_EXAMPLES

logger = logging.getLogger(__name__)


def _format_inputs(inputs: list[dict]) -> str:
    lines = []
    for inp in inputs:
        desc = inp.get("description", "")
        lines.append(f"- {inp['name']} ({inp.get('type', 'string')}): {desc}")
    return "\n".join(lines) if lines else "(none specified)"


def _format_outputs(outputs: list) -> str:
    if not outputs:
        return "(none specified)"
    return "\n".join(f"- {o}" for o in outputs)


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines)
    return stripped.strip()


@mlflow.trace(name="dmn_creator")
def dmn_creator(state: dict) -> dict:
    """Generate DMN 1.4 XML for a decision item."""
    logger.info("── DMN Creator ──")
    item = state.get("item", {})
    source_pages = state.get("source_pages", "")
    abbreviations = state.get("abbreviations", {})
    output_dir = state.get("output_dir", "output")
    syntax_errors = state.get("syntax_errors", [])
    semantic_discrepancies = state.get("semantic_discrepancies", [])

    name = item.get("name", "Unknown Decision")
    description = item.get("description", "")
    category = item.get("category", "treatment")
    hit_policy = item.get("hit_policy", "FIRST")
    inputs = item.get("inputs", [])
    outputs = item.get("outputs", [])

    feedback = ""
    if syntax_errors:
        feedback = "PREVIOUS ATTEMPT HAD SYNTAX ERRORS — fix these:\n" + "\n".join(f"- {e}" for e in syntax_errors)
    elif semantic_discrepancies:
        feedback = "PREVIOUS ATTEMPT HAD SEMANTIC ISSUES — fix these:\n" + "\n".join(f"- {d}" for d in semantic_discrepancies)

    abbr_str = "\n".join(f"- {k}: {v}" for k, v in abbreviations.items()) if abbreviations else "(none)"

    llm = get_llm(state)

    logger.info("Calling LLM...")
    t0 = time.time()
    response = llm.invoke([
        {"role": "system", "content": DMN_CREATOR_SYSTEM.format(reference=REFERENCE_EXAMPLES)},
        {"role": "user", "content": DMN_CREATOR_USER.format(
            name=name,
            description=description,
            category=category,
            hit_policy=hit_policy,
            inputs=_format_inputs(inputs),
            outputs=_format_outputs(outputs),
            source_pages=source_pages,
            abbreviations=abbr_str,
            feedback=feedback,
        )},
    ])
    logger.info("LLM responded in %.1fs", time.time() - t0)

    dmn_xml = _strip_markdown_fences(response.content)

    safe_name = name.lower().replace(" ", "-").replace("/", "-")[:50]
    write_artifact(output_dir, f"dmn/{safe_name}.dmn", dmn_xml)

    review_count = state.get("review_count", 0)
    if syntax_errors or semantic_discrepancies:
        review_count += 1

    logger.info("DMN Creator produced XML for '%s' (%d chars)", name, len(dmn_xml))

    return {
        "dmn_xml": dmn_xml,
        "syntax_errors": [],
        "semantic_discrepancies": [],
        "review_count": review_count,
    }
