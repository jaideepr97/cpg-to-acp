"""Parse a CPG PDF into structured Markdown using Docling."""

import json
import logging
from pathlib import Path

import click
import mlflow

from cpg_ingester.docling_convert import build_converter

logger = logging.getLogger(__name__)


@mlflow.trace(name="parse_cpg_pdf")
def parse_pdf(input_path: Path, output_dir: Path) -> Path:
    """Parse a PDF file and write Markdown + JSON outputs.

    Returns the path to the Markdown output file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem

    # Shared converter config (do_ocr=False) — single source of truth with the
    # pipeline node. See cpg_ingester.docling_convert.
    converter = build_converter(do_ocr=False)
    result = converter.convert(str(input_path))

    md_path = output_dir / f"{stem}.md"
    md_path.write_text(result.document.export_to_markdown())
    logger.info("Wrote Markdown: %s", md_path)

    json_path = output_dir / f"{stem}.json"
    json_path.write_text(json.dumps(result.document.export_to_dict(), indent=2))
    logger.info("Wrote JSON: %s", json_path)

    return md_path


@click.command()
@click.argument("input_pdf", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("output"),
    help="Directory for parsed output files.",
)
def main(input_pdf: Path, output_dir: Path):
    """Parse a CPG PDF into structured Markdown using Docling."""
    logging.basicConfig(level=logging.INFO)
    md_path = parse_pdf(input_pdf, output_dir)
    click.echo(f"Parsed output: {md_path}")


if __name__ == "__main__":
    main()
