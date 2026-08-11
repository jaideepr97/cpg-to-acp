"""Console output formatting and MLflow logging for benchmark results."""

import logging
import subprocess

import mlflow

from acp_writer.benchmark.models import CaseScore, SuiteResult

logger = logging.getLogger(__name__)


def print_summary(result: SuiteResult, verbose: bool = False) -> None:
    """Print a summary table to the console."""
    print(f"\nSuite: {result.suite_name} | Backend: {result.backend_name} | Cases: {result.total}")
    print("=" * 65)
    print(f"{'Category':<22} {'Total':>5} {'Correct':>8} {'Accuracy':>9} {'Halluc.':>8}")
    print("-" * 65)

    for cat_name in sorted(result.by_category):
        cat = result.by_category[cat_name]
        print(
            f"{cat_name:<22} {cat.total:>5} {cat.correct:>8} "
            f"{cat.accuracy:>8.1%} {cat.hallucinations:>8}"
        )

    print("-" * 65)
    print(
        f"{'OVERALL':<22} {result.total:>5} {result.correct:>8} "
        f"{result.accuracy:>8.1%} {result.hallucinations:>8}"
    )
    print(f"\nProvenance accuracy: {result.provenance_accuracy:.1%}")
    print(f"Errors: {result.errors}")

    if verbose:
        _print_case_details(result.case_scores)


def _print_case_details(case_scores: list[CaseScore]) -> None:
    """Print per-case details for verbose mode."""
    print(f"\n{'ID':<30} {'OK':>3} {'Prov':>5} {'Hal':>4} {'Expected':<20} {'Actual':<20}")
    print("-" * 90)

    for cs in case_scores:
        ok = "Y" if cs.correct else "N"
        prov = "Y" if cs.provenance_correct else "N"
        hal = "!" if cs.hallucination else " "
        expected_str = str(cs.expected)[:18]
        actual_str = str(cs.actual)[:18]
        if cs.error:
            actual_str = f"ERR: {cs.error}"[:18]
        print(f"{cs.test_id:<30} {ok:>3} {prov:>5} {hal:>4} {expected_str:<20} {actual_str:<20}")


def log_to_mlflow(result: SuiteResult) -> None:
    """Log benchmark results to MLflow."""
    try:
        git_sha = (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        git_sha = "unknown"

    mlflow.log_params({
        "benchmark_suite": result.suite_name,
        "benchmark_backend": result.backend_name,
        "git_sha": git_sha,
    })

    mlflow.log_metrics({
        "benchmark_accuracy": result.accuracy,
        "benchmark_provenance_accuracy": result.provenance_accuracy,
        "benchmark_hallucinations": result.hallucinations,
        "benchmark_errors": result.errors,
        "benchmark_total": result.total,
        "benchmark_correct": result.correct,
    })

    for cat_name, cat in result.by_category.items():
        mlflow.log_metric(f"benchmark_accuracy_{cat_name}", cat.accuracy)
        mlflow.log_metric(f"benchmark_hallucinations_{cat_name}", cat.hallucinations)
