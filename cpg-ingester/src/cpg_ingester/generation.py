"""DMN and Recommendation generation subgraphs with review loops.

Extracted from pipeline.py to avoid importing Docling in the
LLM Analysis pod. This module only imports DMN/Rec nodes —
no Docling, no structure analyzer, no assembly/delivery.
"""

import logging
import re

from langgraph.graph import END, START, StateGraph

from cpg_ingester.nodes.dmn_creator import dmn_creator
from cpg_ingester.nodes.dmn_semantic_reviewer import dmn_semantic_reviewer
from cpg_ingester.nodes.dmn_syntax_validator import dmn_syntax_validator
from cpg_ingester.nodes.rec_extractor import rec_extractor
from cpg_ingester.nodes.rec_schema_validator import rec_schema_validator
from cpg_ingester.nodes.rec_semantic_reviewer import rec_semantic_reviewer
from cpg_ingester.state import CPGIngesterState, DMNPipelineState, RecPipelineState

logger = logging.getLogger(__name__)

MAX_DMN_REVIEWS = 2


def _extract_section_text(markdown: str, section_map: list, section_id: str) -> str:
    """Extract the markdown text for a section by matching its heading.

    Finds the section heading in the markdown and returns all text from that
    heading to the next heading of equal or higher level.
    """
    if not markdown or not section_id:
        return ""

    matching = [s for s in section_map if section_id in s.get("heading", "")]
    if not matching:
        return ""

    heading = matching[0].get("heading", "")
    lines = markdown.split("\n")

    start_idx = None
    heading_level = 0
    for i, line in enumerate(lines):
        if heading in line and line.strip().startswith("#"):
            start_idx = i
            heading_level = len(line) - len(line.lstrip("#"))
            break

    if start_idx is None:
        return ""

    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        line = lines[i].strip()
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            if level <= heading_level:
                text_after_hash = line.lstrip("#").strip()
                if re.match(r"\d", text_after_hash):
                    end_idx = i
                    break

    return "\n".join(lines[start_idx:end_idx]).strip()
MAX_REC_REVIEWS = 2


# --- DMN subgraph routing ---

def _route_after_dmn_syntax(state: DMNPipelineState) -> str:
    if state.get("syntax_errors"):
        if state.get("review_count", 0) >= MAX_DMN_REVIEWS:
            return "dmn_escalate"
        return "dmn_creator"
    return "dmn_semantic_reviewer"


def _route_after_dmn_semantic(state: DMNPipelineState) -> str:
    if state.get("semantic_discrepancies"):
        if state.get("review_count", 0) >= MAX_DMN_REVIEWS:
            return "dmn_escalate"
        return "dmn_creator"
    return "dmn_accept"


def _dmn_accept(state: DMNPipelineState) -> dict:
    logger.info("DMN accepted: %s", state.get("item", {}).get("name", "unknown"))
    return {"escalated": False}


def _dmn_escalate(state: DMNPipelineState) -> dict:
    logger.warning("DMN escalated for human review: %s", state.get("item", {}).get("name", "unknown"))
    return {"escalated": True}


# --- Rec subgraph routing ---

def _route_after_rec_schema(state: RecPipelineState) -> str:
    if state.get("schema_errors"):
        if state.get("review_count", 0) >= MAX_REC_REVIEWS:
            return "rec_escalate"
        return "rec_extractor"
    return "rec_semantic_reviewer"


def _route_after_rec_semantic(state: RecPipelineState) -> str:
    if state.get("semantic_discrepancies"):
        if state.get("review_count", 0) >= MAX_REC_REVIEWS:
            return "rec_escalate"
        return "rec_extractor"
    return "rec_accept"


def _rec_accept(state: RecPipelineState) -> dict:
    logger.info("Recommendations accepted for section")
    return {"escalated": False}


def _rec_escalate(state: RecPipelineState) -> dict:
    logger.warning("Recommendations escalated for human review")
    return {"escalated": True}


# --- Subgraph builders ---

def _build_dmn_subgraph() -> StateGraph:
    graph = StateGraph(DMNPipelineState)

    graph.add_node("dmn_creator", dmn_creator)
    graph.add_node("dmn_syntax_validator", dmn_syntax_validator)
    graph.add_node("dmn_semantic_reviewer", dmn_semantic_reviewer)
    graph.add_node("dmn_accept", _dmn_accept)
    graph.add_node("dmn_escalate", _dmn_escalate)

    graph.add_edge(START, "dmn_creator")
    graph.add_edge("dmn_creator", "dmn_syntax_validator")
    graph.add_conditional_edges("dmn_syntax_validator", _route_after_dmn_syntax, {
        "dmn_semantic_reviewer": "dmn_semantic_reviewer",
        "dmn_creator": "dmn_creator",
        "dmn_escalate": "dmn_escalate",
    })
    graph.add_conditional_edges("dmn_semantic_reviewer", _route_after_dmn_semantic, {
        "dmn_accept": "dmn_accept",
        "dmn_creator": "dmn_creator",
        "dmn_escalate": "dmn_escalate",
    })
    graph.add_edge("dmn_accept", END)
    graph.add_edge("dmn_escalate", END)

    return graph


def _build_rec_subgraph() -> StateGraph:
    graph = StateGraph(RecPipelineState)

    graph.add_node("rec_extractor", rec_extractor)
    graph.add_node("rec_schema_validator", rec_schema_validator)
    graph.add_node("rec_semantic_reviewer", rec_semantic_reviewer)
    graph.add_node("rec_accept", _rec_accept)
    graph.add_node("rec_escalate", _rec_escalate)

    graph.add_edge(START, "rec_extractor")
    graph.add_edge("rec_extractor", "rec_schema_validator")
    graph.add_conditional_edges("rec_schema_validator", _route_after_rec_schema, {
        "rec_semantic_reviewer": "rec_semantic_reviewer",
        "rec_extractor": "rec_extractor",
        "rec_escalate": "rec_escalate",
    })
    graph.add_conditional_edges("rec_semantic_reviewer", _route_after_rec_semantic, {
        "rec_accept": "rec_accept",
        "rec_extractor": "rec_extractor",
        "rec_escalate": "rec_escalate",
    })
    graph.add_edge("rec_accept", END)
    graph.add_edge("rec_escalate", END)

    return graph


# --- Generation orchestrator ---

def generate_all(state: dict) -> dict:
    """Run DMN and Rec subgraphs for each manifest item.

    Results are stored in state for downstream use (assembly, delivery).
    """
    manifest = state.get("item_manifest", [])
    if not manifest:
        logger.warning("Empty manifest — skipping generation")
        return {}

    markdown = state.get("markdown", "")
    section_map = state.get("section_map", [])

    shared = {
        "abbreviations": state.get("abbreviations", {}),
        "litellm_url": state.get("litellm_url", ""),
        "llm_model": state.get("llm_model", ""),
        "llm_api_key": state.get("llm_api_key", ""),
        "output_dir": state.get("output_dir", ""),
    }

    dmn_graph = _build_dmn_subgraph().compile()
    rec_graph = _build_rec_subgraph().compile()

    dmn_results = []
    decisions = [i for i in manifest if i.get("type") == "decision"]
    for item in decisions:
        logger.info("Generating DMN for: %s", item.get("name", "?"))
        source_text = _extract_section_text(markdown, section_map, item.get("section", ""))
        try:
            result = dmn_graph.invoke({
                "item": item,
                "source_pages": source_text or item.get("source_pages", ""),
                **shared,
            })
            if result.get("dmn_xml") and not result.get("escalated"):
                dmn_results.append({
                    "dmn_xml": result["dmn_xml"],
                    "item": item,
                    "decision_model_summary": result.get("decision_model_summary", {}),
                })
        except Exception as e:
            logger.error("DMN generation failed for '%s': %s", item.get("name"), e)

    all_recs = []
    seen_sections = set()
    recommendations = [i for i in manifest if i.get("type") == "recommendation"]
    for item in recommendations:
        section = item.get("section", "default")
        if section in seen_sections:
            continue
        seen_sections.add(section)
        section_items = [i for i in recommendations if i.get("section") == section]
        logger.info("Extracting recommendations for section: %s (%d items)", section, len(section_items))
        source_text = _extract_section_text(markdown, section_map, section)
        try:
            result = rec_graph.invoke({
                "items": section_items,
                "source_pages": source_text or item.get("source_pages", ""),
                "grading_definitions": state.get("grading_definitions", ""),
                **shared,
            })
            recs = result.get("recommendations", [])
            if recs and not result.get("escalated"):
                all_recs.extend(recs)
        except Exception as e:
            logger.error("Rec extraction failed for section '%s': %s", section, e)

    return {
        "dmn_results": dmn_results,
        "recommendation_results": all_recs,
    }
