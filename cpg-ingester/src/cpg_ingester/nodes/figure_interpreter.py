"""Figure Interpreter — turns extracted figure bitmaps into structured content.

Runs in the **LLM-Analysis pod** (it needs LLM egress; the
ingestion pod has none). It is deliberately kept as a **separated / decoupled
agent**: its own module with no coupling to the other analysis nodes
(structure_analyzer, item_identifier, …) so it can be lifted into its own pod
later without untangling shared code. Its only inputs are the parse result's
``figures`` index, ``markdown``, and ``docling_json``; its only output is an
enriched ``markdown`` (+ the ``figures`` index annotated with interpretations).

Type-conditional:
  - ``flow_chart`` → a validated Mermaid ``flowchart`` + prose description.
  - other substantive classes → prose description only.
  - trivial classes (logos/stamps/…) → a cheap label, no LLM call.

Each interpretation is spliced back into the markdown at the figure's own
location by **positional placeholder matching**: docling emits one
``<!-- image -->`` per picture in reading order and the ``figures`` index is
built in that same order, so the k-th placeholder is the k-th figure. Two guards
protect that assumption — a count guard (placeholders == figures) and a
``self_ref`` order guard (body picture order == figures index order) — and a
count/order mismatch falls back to a "Figure Interpretations" appendix rather
than risk attaching an interpretation to the wrong figure. See
``_inline_interpretations``.

The vision path was de-risked with an earlier prototype: a vision LLM recovered
flowcharts at full node/edge fidelity with valid, distinct Mermaid tied to the
right figure. The benchmark's ``--interpret`` mode re-scores this end-to-end
against synthetic fixtures with per-figure ground truth.
"""

import logging
import re

import mlflow

from cpg_contracts import content_to_text, get_artifact_store, get_llm
from cpg_ingester.env_utils import env_flag, env_int
from cpg_ingester.nodes.structure_analyzer import _parse_llm_json
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
    Empty/unset → default (on).
    """
    return env_flag("FIGURE_INTERPRETATION_ENABLED", default=True)


# Default ceiling on vision calls per document — a pathological figure
# compendium must not fan out into hundreds of frontier-model calls.
DEFAULT_MAX_FIGURES = 100


def _max_figures() -> int:
    """Max figures that may get an LLM call per document.

    ``FIGURE_INTERPRETATION_MAX_FIGURES`` overrides; empty/unset/unparseable →
    ``DEFAULT_MAX_FIGURES``. Trivial-class label-only figures do not count
    against this budget (they make no LLM call).
    """
    return env_int("FIGURE_INTERPRETATION_MAX_FIGURES", DEFAULT_MAX_FIGURES)


def _classification(fig: dict) -> str:
    return (fig.get("classification") or "").strip().lower()


def _is_flowchart(cls: str) -> bool:
    return cls in FLOWCHART_CLASSES or "flow" in cls


def _is_trivial(cls: str) -> bool:
    return cls in TRIVIAL_CLASSES


def _resolve_figure_png_b64(
    fig: dict, figure_images: dict[str, str], store=None
) -> str | None:
    """Return the figure's base64-PNG, or None if no bitmap can be resolved.

    Handles every way a bitmap can reach this node:
      1. ``figure_images`` passed inline in state (in-process LangGraph run).
      2. ``image_b64`` carried on the figure entry (local/no-store mode).
      3. ``image_ref`` in the artifact store (distributed pod mode). The caller
         resolves the store **once** and passes it in as ``store`` — this helper
         never constructs one, so an offline document (no ``image_ref``) does no
         store round-trips.
    """
    fid = fig.get("id", "")
    if fid and figure_images.get(fid):
        return figure_images[fid]
    if fig.get("image_b64"):
        return fig["image_b64"]

    ref = fig.get("image_ref")
    if ref:
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


def _validate_mermaid(mermaid: str) -> tuple[bool, str]:
    """Validate a Mermaid flowchart structurally. Returns ``(ok, detail)``.

    The check is deliberately **structural-only**: a ``flowchart``/``graph``
    header plus at least one ``-->`` edge. There is no ``mmdc`` render step — the
    CLI is in no image and no requirement, so a render path would never run in
    practice, and if one ever appeared it would shell out to Chromium on
    unsanitized LLM output without a timeout. The safety net that actually
    matters is the caller degrading to description-only when this returns
    ``False`` (see ``_interpret_one``), so a lightweight well-formedness check is
    enough — we never emit Mermaid that fails it.
    """
    if not (mermaid and mermaid.strip()):
        return False, "empty mermaid"

    head = mermaid.strip().splitlines()[0].strip()
    if not re.match(r"^(flowchart|graph)\s+\w+", head):
        return False, f"structural: bad header {head!r}"
    if "-->" not in mermaid:
        return False, "structural: no edges (-->)"
    return True, "structural: header + edges present"


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
    parsed = _parse_llm_json(content_to_text(resp.content))
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")

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


def _body_picture_order(docling_json: dict) -> list[str]:
    """Picture refs (``#/pictures/N``) in document body reading order.

    Walks ``docling_json["body"]["children"]`` and collects the picture
    references in the order they appear. Returns ``[]`` when the body/children
    structure is absent (e.g. the minimal states some unit tests seed) so
    callers can skip the order check and fall back to positional behavior.
    """
    body = (docling_json or {}).get("body") or {}
    children = body.get("children") or []
    refs: list[str] = []
    for child in children:
        ref = child.get("$ref") or child.get("cref") if isinstance(child, dict) else None
        if isinstance(ref, str) and ref.startswith("#/pictures/"):
            refs.append(ref)
    return refs


def _inline_interpretations(
    markdown: str,
    figures: list[dict],
    interps: dict[str, dict],
    docling_json: dict | None = None,
) -> str:
    """Splice each figure's interpretation into the markdown at its own location.

    Mechanism: docling emits one ``<!-- image -->`` placeholder per picture in
    reading order, and the ``figures`` index is built in that same order, so the
    k-th placeholder corresponds to the k-th figure. We splice **positionally**
    against those placeholders. Two guards protect the positional assumption:

    1. **Count guard** — splice only when the placeholder count equals the
       figure count. A mismatch (a picture without a placeholder, or vice versa)
       means positions can't be trusted.
    2. **Order guard** — when ``docling_json`` is available, reconstruct the
       picture order from ``body.children`` and require it to match the figures
       index's ``self_ref`` order. A disagreement means a positional splice
       could attach an interpretation to the *wrong* figure (the clinically
       dangerous case), so we don't.

    If either guard fails we fall back to a "Figure Interpretations" appendix so
    nothing is mis-placed or lost. ``self_ref`` is used here as a **verification
    anchor**, not as a splice key (the splice is positional). The figures index
    is already in reading order, so we use it as-is.
    """
    ordered = figures  # the figures index is already in document reading order
    parts = markdown.split(IMAGE_PLACEHOLDER)
    placeholder_count = len(parts) - 1

    # Order guard: only enforced when we can reconstruct body order.
    order_ok = True
    body_order = _body_picture_order(docling_json or {})
    if body_order:
        fig_refs = [f.get("self_ref") for f in ordered]
        if any(r is None for r in fig_refs) or body_order != fig_refs:
            order_ok = False
            logger.warning(
                "Figure body order %s disagrees with figures index order %s; "
                "using an appendix instead of a positional splice",
                body_order, fig_refs,
            )

    if order_ok and placeholder_count == len(ordered) and placeholder_count > 0:
        out = [parts[0]]
        for k, fig in enumerate(ordered):
            interp = interps.get(fig.get("id", ""))
            out.append(_render_block(fig, interp) if interp else IMAGE_PLACEHOLDER)
            out.append(parts[k + 1])
        return "".join(out)

    # Fallback: a guard failed — append an appendix instead of guessing.
    if interps:
        logger.warning(
            "Figure placeholder count (%d) vs figure count (%d), order_ok=%s; "
            "appending interpretations as an appendix instead of inlining",
            placeholder_count, len(ordered), order_ok,
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
    max_figures = _max_figures()
    interps: dict[str, dict] = {}
    interpreted = skipped_trivial = skipped_no_bitmap = failed = capped = already = 0
    llm_calls = 0  # figures that made (or attempted) a vision call — the budget
    total_tokens = 0

    # Resolve the artifact store once, and only if some figure actually needs it
    # (an image_ref that isn't already inline) — offline runs stay store-free
    # instead of paying an N× boto3-client + head_bucket round-trip.
    needs_store = any(
        f.get("image_ref")
        and not (figure_images.get(f.get("id", "")) or f.get("image_b64"))
        for f in figures
    )
    store = get_artifact_store() if needs_store else None

    for fig in figures:
        fid = fig.get("id", "")
        cls = _classification(fig)

        # Idempotency: a figure already carrying an interpretation
        # (e.g. re-fed from a cached enriched parse) must never trigger a second
        # vision call. The caller owns the already-enriched markdown, so we do
        # not re-splice — just skip.
        if fig.get("interpretation"):
            already += 1
            continue

        if _is_trivial(cls):
            fig["interpretation"] = {"label": cls}
            skipped_trivial += 1
            continue

        b64 = _resolve_figure_png_b64(fig, figure_images, store)
        if not b64:
            skipped_no_bitmap += 1
            continue

        # Cap the number of vision calls per document. Only figures
        # that would actually call the LLM count against the budget; trivial and
        # no-bitmap figures above do not. Capped figures get no interpretation —
        # the positional splice re-emits their bare placeholder.
        if llm_calls >= max_figures:
            capped += 1
            continue
        llm_calls += 1

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

    markdown = _inline_interpretations(
        markdown, figures, interps, state.get("docling_json")
    )

    if capped:
        # No-silent-caps: say exactly how many figures were left uninterpreted.
        logger.warning(
            "Figure-interpretation cap reached (FIGURE_INTERPRETATION_MAX_FIGURES=%d): "
            "%d figure(s) left uninterpreted", max_figures, capped,
        )
    logger.info(
        "Figure interpretation: %d interpreted, %d already-interpreted, "
        "%d trivial, %d no-bitmap, %d failed, %d capped (%d tokens)",
        interpreted, already, skipped_trivial, skipped_no_bitmap, failed, capped,
        total_tokens,
    )
    span = mlflow.get_current_active_span()
    if span is not None:
        span.set_attributes({
            "figure_interp.interpreted": interpreted,
            "figure_interp.already": already,
            "figure_interp.trivial": skipped_trivial,
            "figure_interp.no_bitmap": skipped_no_bitmap,
            "figure_interp.failed": failed,
            "figure_interp.capped": capped,
            "figure_interp.total_tokens": total_tokens,
        })

    output_dir = state.get("output_dir")
    if output_dir and interps:
        write_artifact(output_dir, "parsed-with-figures.md", markdown)

    return {"markdown": markdown, "figures": figures}
