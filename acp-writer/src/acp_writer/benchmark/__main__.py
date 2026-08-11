"""CLI entry point for the clinical QA benchmark harness.

Usage: python -m acp_writer.benchmark run --suite smoke --backend current
"""

import logging
import os

import click

from acp_writer.benchmark.backends import BACKENDS
from acp_writer.benchmark.report import log_to_mlflow, print_summary
from acp_writer.benchmark.runner import available_suites, run_suite


@click.group()
def cli():
    """Clinical QA benchmark harness for acp-writer."""
    pass


@cli.command()
@click.option("--suite", required=True, help="Suite name (e.g. 'smoke').")
@click.option("--backend", default="current", help="Backend name (e.g. 'current').")
@click.option("--tolerance", default=0.0, type=float, help="Numeric tolerance for number comparisons.")
@click.option("--log-mlflow/--no-mlflow", default=True, help="Log results to MLflow.")
@click.option("--verbose", "-v", is_flag=True, help="Print per-case results.")
def run(suite: str, backend: str, tolerance: float, log_mlflow: bool, verbose: bool):
    """Run a benchmark suite against a backend."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if backend not in BACKENDS:
        raise click.BadParameter(
            f"Unknown backend: {backend}. Available: {', '.join(BACKENDS)}",
            param_hint="--backend",
        )

    if not log_mlflow:
        os.environ.setdefault("MLFLOW_TRACKING_URI", "file:///tmp/mlflow-benchmark")

    backend_instance = BACKENDS[backend]()
    result = run_suite(suite, backend_instance, tolerance)
    print_summary(result, verbose=verbose)

    if log_mlflow:
        try:
            log_to_mlflow(result)
            click.echo("\nResults logged to MLflow.")
        except Exception as exc:
            click.echo(f"\nMLflow logging failed (results still printed above): {exc}")


@cli.command(name="list")
def list_cmd():
    """List available suites and backends."""
    click.echo("Suites:")
    for s in available_suites():
        click.echo(f"  {s}")

    click.echo("\nBackends:")
    for b in BACKENDS:
        click.echo(f"  {b}")


if __name__ == "__main__":
    cli()
