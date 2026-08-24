"""Offline tests for the figure-interpretation benchmark scorer.

Only the pure scoring helpers are exercised here — ``score_figures`` itself is
live (docling + vision LLM) and runs via ``run_benchmark.py --interpret``.
"""

import sys
from pathlib import Path

_BENCH = Path(__file__).parent / "benchmarks" / "parsing"
sys.path.insert(0, str(_BENCH))

import interpret_metrics as im  # noqa: E402


class TestFigureGroundtruth:
    def test_per_figure_by_reading_order_index(self):
        gt = {
            "figures": [
                {"index": 0, "heading": "A", "flowchart_nodes": ["x"]},
                {"index": 1, "heading": "B", "flowchart_nodes": ["y"]},
            ]
        }
        block, source = im._figure_groundtruth(gt, {"id": "fig-002", "reading_order_index": 1})
        assert block["heading"] == "B"
        assert "figures[1]" in source

    def test_falls_back_to_id_when_no_index(self):
        gt = {"figures": [{"index": 0, "heading": "A"}, {"index": 1, "heading": "B"}]}
        block, _ = im._figure_groundtruth(gt, {"id": "fig-001"})
        assert block["heading"] == "A"

    def test_top_level_when_no_per_figure(self):
        gt = {"flowchart_nodes": ["a", "b"]}
        block, source = im._figure_groundtruth(gt, {"id": "fig-001"})
        assert block is gt
        assert source == "top-level flowchart_*"


class TestScoreOne:
    def test_scores_node_recovery(self):
        fig = {
            "id": "fig-001",
            "classification": "flow_chart",
            "reading_order_index": 0,
            "interpretation": {
                "mermaid_valid": True,
                "nodes": ["Start treatment", "Decision point", "Stop"],
                "edges": [["a", "b", "Yes"]],
                "description": "walk",
            },
        }
        gt = {"figures": [{"index": 0, "heading": "A",
                           "flowchart_nodes": ["Start treatment", "Decision point", "Stop"],
                           "flowchart_edges": [["a", "b", "Yes"]]}]}
        row = im._score_one(fig, gt)
        assert row["gt_node_count"] == 3
        assert row["node_label_matches"] == 3
        assert row["recovered_edge_count"] == 1
        assert row["gt_edge_count"] == 1
        assert row["mermaid_valid"] is True
        assert row["has_description"] is True

    def test_partial_match(self):
        fig = {
            "id": "fig-001",
            "reading_order_index": 0,
            "interpretation": {"nodes": ["Start"], "edges": []},
        }
        gt = {"figures": [{"index": 0, "flowchart_nodes": ["Start", "Middle", "End"]}]}
        row = im._score_one(fig, gt)
        assert row["gt_node_count"] == 3
        assert row["node_label_matches"] == 1
