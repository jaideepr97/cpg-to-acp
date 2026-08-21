"""Figure Interpreter — turns extracted figure bitmaps into structured content.

Plan P5 (part 2). Runs in the **LLM-Analysis pod** (it needs LLM egress; the
ingestion pod has none). It is deliberately kept as a **separated / decoupled
agent**: its own module with no coupling to the other analysis nodes
(structure_analyzer, item_identifier, …) so it can be lifted into its own pod
later without untangling shared code. Its only inputs are the parse result's
``figures`` index, ``markdown``, and ``docling_json``; its only output is an
enriched ``markdown`` (+ the ``figures`` index annotated with interpretations).

Type-conditional (review §10 D4):
  - ``flow_chart`` → a validated Mermaid ``flowchart`` + prose description.
  - other substantive classes → prose description only.
  - trivial classes (logos/stamps/…) → a cheap label, no LLM call.

Each interpretation is spliced back into the markdown **at the figure's own
location** using docling reading order (the picture ``self_ref`` /
``reading_order_index``), never the anonymous ``<!-- image -->`` comment as an
identity — see ``_inline_interpretations``.

The vision path was de-risked in the P5a spike
(``working/RHAIENG-6461-docling-review/``): gpt-5.6 recovered flowcharts at
7/7 nodes/edges with valid, distinct Mermaid tied to the right figure.
"""

import json
import logging
import os
import re

import mlflow

from cpg_contracts import content_to_text, get_artifact_store, get_llm
from cpg_ingester.output import write_artifact
from cpg_ingester.prompts.figure_interpreter import (
    DESCRIPTION_ONLY_USER,
    FIGURE_SYSTEM,
    FLOWCHART_USER,
)

logger = logging.getLogger(__name__)

# The docling markdown placeholder emitted for every picture region.
IMAGE_PLACEHOLDER = "<!-- image -->"

# Figure classes (from docling's picture classifier) that get a Mermaid diagram.
FLOWCHART_CLASSES = {"flow_chart"}

# Trivial classes not worth an LLM call — a cheap label is enough. Everything
# not listed here (and not a flowchart) gets a description-only vision call.
TRIVIAL_CLASSES = {"logo", "signature", "stamp", "icon"}


def _interpretation_enabled() -> bool:
    """Whether the figure-interpretation node does any LLM work.

    On by default; set ``FIGURE_INTERPRETATION_ENABLED`` to a falsey value
    (``0``/``false``/``no``/``off``) to skip all vision calls (e.g. a
    cost-sensitive or offline run) — figures are then left as-is.
    """
    return os.environ.get("FIGURE_INTERPRETATION_ENABLED", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _classification(fig: dict) -> str:
    return (fig.get("classification") or "").strip().lower()


def _is_flowchart(cls: str) -> bool:
    return cls in FLOWCHART_CLASSES or "flow" in cls


def _is_trivial(cls: str) -> bool:
    return cls in TRIVIAL_CLASSES


def _resolve_figure_png_b64(fig: dict, figure_images: dict[str, str]) -> str | None:
    """Return the figure's base64-PNG, or None if no bitmap can be resolved.

    Handles every way a bitmap can reach this node:
      1. ``figure_images`` passed inline in state (in-process LangGraph run).
      2. ``image_b64`` carried on the figure entry (local/no-store mode).
      3. ``image_ref`` in the artifact store (distributed pod mode).
    """
    fid = fig.get("id", "")
    if fid and figure_images.get(fid):
        return figure_images[fid]
    if fig.get("image_b64"):
        return fig["image_b64"]

    ref = fig.get("image_ref")
    if ref:
        store = get_artifact_store()
        if store is None:
            logger.warning(
                "Figure %s has image_ref but no artifact store is configured; "
                "cannot resolve bitmap", fid,
            )
            return None
        try:
            import base64

            return base64.b64encode(store.get_raw(ref)).decode("ascii")
        except Exception as e:  # noqa: BLE001 — resolution is best-effort
            logger.warning("Failed to resolve figure %s bitmap from %s: %s", fid, ref, e)
            return None
    return None


def _parse_json_object(text: str) -> dict:
    """Extract the first JSON object from a model reply (tolerates code fences)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, depth = text.find("{"), 0
        if start >= 0:
            for i in range(start, len(text)):
                depth += (text[i] == "{") - (text[i] == "}")
                if depth == 0:
                    return json.loads(text[start : i + 1])
    raise ValueError("no JSON object found in model reply")


def _validate_mermaid(mermaid: str) -> tuple[bool, str]:
    """Validate a Mermaid block. Prefer the ``mmdc`` CLI; fall back to structure.

    Returns ``(ok, detail)``. The structural fallback confirms the block is
    plausibly well-formed (a ``flowchart``/``graph`` header + at least one
    ``-->`` edge) when ``mmdc`` is not installed — the common runtime case.
    On failure the node degrades to description-only rather than emit broken
    Mermaid, which is the whole point of validating.
    """
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    if not (mermaid and mermaid.strip()):
        return False, "empty mermaid"

    mmdc = shutil.which("mmdc")
    if mmdc:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "d.mmd"
            src.write_text(mermaid)
            out = Path(tmp) / "d.svg"
            proc = subprocess.run(
                [mmdc, "-i", str(src), "-o", str(out)],
                capture_output=True, text=True,
            )
            if proc.returncode == 0 and out.exists():
                return True, "mmdc: rendered OK"
            return False, f"mmdc: {proc.stderr.strip()[:200]}"

    head = mermaid.strip().splitlines()[0].strip()
    if not re.match(r"^(flowchart|graph)\s+\w+", head):
        return False, f"structural: bad header {head!r}"
    if "-->" not in mermaid:
        return False, "structural: no edges (-->)"
    return True, "structural: header + edges present (mmdc not installed)"


def _build_messages(fig: dict, b64png: str):
    """Build ``(messages, is_flowchart)`` for the vision call."""
    from langchain_core.messages import HumanMessage, SystemMessage

    cls = _classification(fig)
    is_flow = _is_flowchart(cls)
    text = FLOWCHART_USER if is_flow else DESCRIPTION_ONLY_USER.format(cls=cls or "figure")
    human = HumanMessage(
        content=[
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64png}"}},
        ]
    )
    return [SystemMessage(content=FIGURE_SYSTEM), human], is_flow


def _interpret_one(llm, fig: dict, b64png: str) -> dict:
    """Interpret a single figure. Returns an interpretation dict (may be partial).

    Keys: ``description`` (always, on success), and for flowcharts ``mermaid``,
    ``mermaid_valid``, ``mermaid_detail``, ``nodes``, ``edges``.
    """
    messages, is_flow = _build_messages(fig, b64png)
    resp = llm.invoke(messages)
    parsed = _parse_json_object(content_to_text(resp.content))

    interp: dict = {"description": (parsed.get("description") or "").strip()}
    usage = getattr(resp, "usage_metadata", None)
    if usage:
        interp["_tokens"] = usage.get("total_tokens")

    if is_flow:
        mermaid = (parsed.get("mermaid") or "").strip()
        ok, detail = _validate_mermaid(mermaid)
        interp["mermaid_valid"] = ok
        interp["mermaid_detail"] = detail
        interp["nodes"] = parsed.get("nodes") or []
        interp["edges"] = parsed.get("edges") or []
        if ok:
            interp["mermaid"] = mermaid
        else:
            # Degrade gracefully: keep the description, drop broken Mermaid.
            logger.warning("Figure %s Mermaid invalid (%s) — description only",
                           fig.get("id"), detail)
    return interp


def _render_block(fig: dict, interp: dict) -> str:
    """Render an interpreted figure as a markdown block (replaces the placeholder)."""
    cls = _classification(fig) or "figure"
    page = fig.get("page")
    where = f", page {page}" if page else ""
    lines = [
        f"<!-- figure {fig['id']} ({cls}{where}) -->",
        "",
        f"**Figure {fig['id']} — {cls}{where}.** {interp.get('description', '')}".rstrip(),
    ]
    if interp.get("mermaid") and interp.get("mermaid_valid"):
        lines += ["", "```mermaid", interp["mermaid"].strip(), "```"]
    return "\n".join(lines)


def _ordered_figures(figures: list[dict]) -> list[dict]:
    """Figures in document reading order (by ``reading_order_index``, then id)."""
    return sorted(
        figures,
        key=lambda f: (
            f.get("reading_order_index")
            if isinstance(f.get("reading_order_index"), int)
            else _fig_num(f),
        ),
    )


def _fig_num(fig: dict) -> int:
    try:
        return int(str(fig.get("id", "fig-000")).split("-")[1])
    except (IndexError, ValueError):
        return 0


def _inline_interpretations(
    markdown: str, figures: list[dict], interps: dict[str, dict]
) -> str:
    """Splice each figure's interpretation into the markdown at its own location.

    docling emits one ``<!-- image -->`` per picture in reading order, and the
    ``figures`` index is in that same order, so the k-th placeholder is the k-th
    figure. We splice positionally **only when the counts match** — if they
    don't (a picture rendered without a placeholder, or vice versa), we fall
    back to a "Figure Interpretations" appendix so nothing is mis-placed or
    lost. This is why we never treat the placeholder itself as a figure's
    identity.
    """
    ordered = _ordered_figures(figures)
    parts = markdown.split(IMAGE_PLACEHOLDER)
    placeholder_count = len(parts) - 1

    if placeholder_count == len(ordered) and placeholder_count > 0:
        out = [parts[0]]
        for k, fig in enumerate(ordered):
            interp = interps.get(fig.get("id", ""))
            out.append(_render_block(fig, interp) if interp else IMAGE_PLACEHOLDER)
            out.append(parts[k + 1])
        return "".join(out)

    # Fallback: counts disagree — append an appendix instead of guessing.
    if interps:
        logger.warning(
            "Figure placeholder count (%d) != figure count (%d); appending "
            "interpretations as an appendix instead of inlining",
            placeholder_count, len(ordered),
        )
        appendix = ["", "## Figure Interpretations", ""]
        for fig in ordered:
            interp = interps.get(fig.get("id", ""))
            if interp:
                appendix += [_render_block(fig, interp), ""]
        return markdown + "\n".join(appendix)
    return markdown


@mlflow.trace(name="figure_interpreter")
def figure_interpreter(state: dict) -> dict:
    """Interpret extracted figures and inline the results into the markdown.

    Reads ``figures``, ``markdown``, ``figure_images`` (optional) from state.
    Returns ``{"markdown": ..., "figures": ...}`` with figures annotated with an
    ``interpretation`` and the markdown enriched in place. A no-op (returns the
    inputs unchanged) when there are no figures or interpretation is disabled.
    """
    logger.info("── Figure Interpreter ──")
    figures = state.get("figures", []) or []
    markdown = state.get("markdown", "")
    figure_images = state.get("figure_images", {}) or {}

    if not figures:
        logger.info("No figures to interpret")
        return {"markdown": markdown, "figures": figures}

    if not _interpretation_enabled():
        logger.info("Figure interpretation disabled (FIGURE_INTERPRETATION_ENABLED)")
        return {"markdown": markdown, "figures": figures}

    llm = get_llm(state)
    interps: dict[str, dict] = {}
    interpreted = skipped_trivial = skipped_no_bitmap = failed = 0
    total_tokens = 0

    for fig in figures:
        fid = fig.get("id", "")
        cls = _classification(fig)

        if _is_trivial(cls):
            fig["interpretation"] = {"label": cls}
            skipped_trivial += 1
            continue

        b64 = _resolve_figure_png_b64(fig, figure_images)
        if not b64:
            skipped_no_bitmap += 1
            continue

        try:
            interp = _interpret_one(llm, fig, b64)
        except Exception as e:  # noqa: BLE001 — one bad figure must not fail the run
            logger.warning("Figure %s interpretation failed: %s", fid, e)
            failed += 1
            continue

        total_tokens += interp.pop("_tokens", None) or 0
        fig["interpretation"] = interp
        interps[fid] = interp
        interpreted += 1

    markdown = _inline_interpretations(markdown, figures, interps)

    logger.info(
        "Figure interpretation: %d interpreted, %d trivial, %d no-bitmap, "
        "%d failed (%d tokens)",
        interpreted, skipped_trivial, skipped_no_bitmap, failed, total_tokens,
    )
    span = mlflow.get_current_active_span()
    if span is not None:
        span.set_attributes({
            "figure_interp.interpreted": interpreted,
            "figure_interp.trivial": skipped_trivial,
            "figure_interp.no_bitmap": skipped_no_bitmap,
            "figure_interp.failed": failed,
            "figure_interp.total_tokens": total_tokens,
        })

    output_dir = state.get("output_dir")
    if output_dir and interps:
        write_artifact(output_dir, "parsed-with-figures.md", markdown)

    return {"markdown": markdown, "figures": figures}
