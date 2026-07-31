"""Extract DMN decision tables from parsed CPG Markdown using an LLM."""

import logging
from pathlib import Path

import click
import mlflow
from openai import OpenAI

mlflow.openai.autolog()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a clinical decision logic engineer. Given a clinical practice guideline \
in Markdown format, extract each decision table into a standalone DMN 1.3 XML file.

Rules:
- Output ONLY valid DMN XML. No explanation, no markdown fences, no commentary.
- Use the DMN 1.3 namespace: https://www.omg.org/spec/DMN/20191111/MODEL/
- Each decision table should be a separate <definitions> document.
- Use FEEL for input/output expressions.
- Use string, number, and boolean types as appropriate.
- Input columns use FEEL unary tests (e.g., >=140, "Yes", true).
- Mark the hit policy as FIRST (F) since rules have priority ordering.
- Keep it simple — no BKMs or complex DRDs.

Structure requirements (the decision engine needs these to wire inputs):
- Each input MUST have a top-level <inputData> element with a <variable> child.
- Each <decision> MUST contain <informationRequirement> elements with \
<requiredInput href="#inputDataId"/> linking to the <inputData> elements.
- The <decision> MUST also have a <variable> child declaring its output.

Example structure:
  <inputData id="input_bp" name="Systolic BP">
    <variable name="Systolic BP" typeRef="number"/>
  </inputData>
  <decision id="decision_1" name="BP Assessment">
    <variable name="BP Assessment" typeRef="string"/>
    <informationRequirement>
      <requiredInput href="#input_bp"/>
    </informationRequirement>
    <decisionTable hitPolicy="FIRST">...</decisionTable>
  </decision>
"""

USER_PROMPT_TEMPLATE = """\
Extract all decision tables from the following clinical practice guideline. \
Return each table as a separate DMN XML document, separated by the line:
---DMN_SEPARATOR---

Guideline content:

{cpg_markdown}
"""


@mlflow.trace(name="extract_dmn")
def extract_dmn(cpg_markdown: str, client: OpenAI, model: str) -> list[str]:
    """Send parsed CPG to LLM and return a list of DMN XML strings."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(cpg_markdown=cpg_markdown)},
        ],
        temperature=0,
        max_tokens=8192,
    )

    raw = response.choices[0].message.content
    dmn_docs = [doc.strip() for doc in raw.split("---DMN_SEPARATOR---") if doc.strip()]
    return dmn_docs


@click.command()
@click.argument("input_markdown", type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=Path("output"))
@click.option("--litellm-url", default="http://localhost:4000", help="LiteLLM proxy URL.")
@click.option("--model", default="default", help="Model name configured in LiteLLM.")
@click.option("--api-key", default="sk-change-me", help="LiteLLM master key.")
@click.option("--deploy", is_flag=True, help="Push extracted DMN to acp-writer after writing.")
@click.option("--acp-writer-url", default="http://localhost:8082", help="ACP Writer URL (used with --deploy).")
@click.option("--source-cpg", default=None, help="CPG ID to link deployed models to (used with --deploy).")
def main(input_markdown: Path, output_dir: Path, litellm_url: str, model: str, api_key: str, deploy: bool, acp_writer_url: str, source_cpg: str | None):
    """Extract DMN decision tables from parsed CPG Markdown."""
    logging.basicConfig(level=logging.INFO)

    output_dir.mkdir(parents=True, exist_ok=True)
    cpg_markdown = input_markdown.read_text()

    client = OpenAI(base_url=f"{litellm_url}/v1", api_key=api_key)
    logger.info("Extracting DMN from %s via %s (model=%s)", input_markdown, litellm_url, model)

    dmn_docs = extract_dmn(cpg_markdown, client, model)
    logger.info("Extracted %d DMN document(s)", len(dmn_docs))

    out_paths = []
    for i, dmn_xml in enumerate(dmn_docs):
        out_path = output_dir / f"decision-table-{i + 1}.dmn"
        out_path.write_text(dmn_xml)
        logger.info("Wrote: %s", out_path)
        click.echo(f"  {out_path}")
        out_paths.append(out_path)

    if deploy:
        from cpg_ingester.deploy import deploy_dmn
        click.echo(f"\nDeploying to {acp_writer_url}...")
        for out_path in out_paths:
            summary = deploy_dmn(out_path, acp_writer_url, source_cpg=source_cpg)
            click.echo(f"  Deployed: {summary.name} ({summary.id})")


if __name__ == "__main__":
    main()
