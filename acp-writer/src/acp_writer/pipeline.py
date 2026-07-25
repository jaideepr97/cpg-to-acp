"""LangGraph pipeline for care plan composition.

Two-phase architecture:
  Phase 1 (Clinical Reasoning): condition_scanner → guideline_resolver →
    dmn_executor → recommendation_retriever → plan_composer → brief_reviewer
  Phase 2 (FHIR Generation): fhir_bundle_generator →
    [terminology_validator ∥ fhir_syntax_validator] →
    fhir_semantic_reviewer → fhir_server_writer
"""

import logging

from langgraph.graph import END, START, StateGraph

from acp_writer.nodes.brief_reviewer import brief_reviewer
from acp_writer.nodes.condition_scanner import condition_scanner
from acp_writer.nodes.dmn_executor import dmn_executor
from acp_writer.nodes.fhir_bundle_generator import fhir_bundle_generator
from acp_writer.nodes.fhir_semantic_reviewer import fhir_semantic_reviewer
from acp_writer.nodes.fhir_server_writer import fhir_server_writer
from acp_writer.nodes.fhir_syntax_validator import fhir_syntax_validator
from acp_writer.nodes.guideline_resolver import guideline_resolver
from acp_writer.nodes.plan_composer import plan_composer
from acp_writer.nodes.recommendation_retriever import recommendation_retriever
from acp_writer.nodes.terminology_validator import terminology_validator
from acp_writer.state import CarePlanComposerState

logger = logging.getLogger(__name__)

MAX_BRIEF_REVIEWS = 4
MAX_FHIR_REVIEWS = 4


# --- Stub nodes ---
# Each stub logs and passes state through. Real implementations in nodes/.



# --- Routing ---


def _route_after_brief_review(state: CarePlanComposerState) -> str:
    feedback = state.get("brief_review_feedback")
    if not feedback:
        return "fhir_bundle_generator"
    if state.get("brief_review_count", 0) >= MAX_BRIEF_REVIEWS:
        logger.warning("Brief review exhausted after %d iterations", MAX_BRIEF_REVIEWS)
        return "fhir_bundle_generator"
    return "plan_composer"


def _route_after_fhir_review(state: CarePlanComposerState) -> str:
    feedback = state.get("fhir_review_feedback")
    if not feedback:
        return "fhir_server_writer"
    if state.get("fhir_review_count", 0) >= MAX_FHIR_REVIEWS:
        logger.warning("FHIR review exhausted after %d iterations", MAX_FHIR_REVIEWS)
        return "fhir_server_writer"
    return "fhir_bundle_generator"


# --- Pipeline builder ---


def build_pipeline() -> StateGraph:
    """Build the full care plan composition pipeline graph."""
    graph = StateGraph(CarePlanComposerState)

    # Phase 1: Clinical Reasoning
    graph.add_node("condition_scanner", condition_scanner)
    graph.add_node("guideline_resolver", guideline_resolver)
    graph.add_node("dmn_executor", dmn_executor)
    graph.add_node("recommendation_retriever", recommendation_retriever)
    graph.add_node("plan_composer", plan_composer)
    graph.add_node("brief_reviewer", brief_reviewer)

    # Phase 2: FHIR Generation
    graph.add_node("fhir_bundle_generator", fhir_bundle_generator)
    graph.add_node("terminology_validator", terminology_validator)
    graph.add_node("fhir_syntax_validator", fhir_syntax_validator)
    graph.add_node("fhir_semantic_reviewer", fhir_semantic_reviewer)
    graph.add_node("fhir_server_writer", fhir_server_writer)

    # Phase 1 edges (sequential with brief review loop)
    graph.add_edge(START, "condition_scanner")
    graph.add_edge("condition_scanner", "guideline_resolver")
    graph.add_edge("guideline_resolver", "dmn_executor")
    graph.add_edge("dmn_executor", "recommendation_retriever")
    graph.add_edge("recommendation_retriever", "plan_composer")
    graph.add_edge("plan_composer", "brief_reviewer")
    graph.add_conditional_edges(
        "brief_reviewer",
        _route_after_brief_review,
        {
            "fhir_bundle_generator": "fhir_bundle_generator",
            "plan_composer": "plan_composer",
        },
    )

    # Phase 2 edges (validators in parallel, then FHIR review loop)
    graph.add_edge("fhir_bundle_generator", "terminology_validator")
    graph.add_edge("fhir_bundle_generator", "fhir_syntax_validator")
    graph.add_edge("terminology_validator", "fhir_semantic_reviewer")
    graph.add_edge("fhir_syntax_validator", "fhir_semantic_reviewer")
    graph.add_conditional_edges(
        "fhir_semantic_reviewer",
        _route_after_fhir_review,
        {
            "fhir_server_writer": "fhir_server_writer",
            "fhir_bundle_generator": "fhir_bundle_generator",
        },
    )
    graph.add_edge("fhir_server_writer", END)

    return graph
