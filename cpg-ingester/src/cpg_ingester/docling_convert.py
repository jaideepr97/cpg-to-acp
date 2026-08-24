"""Shared Docling ``DocumentConverter`` construction.

Single source of truth for how cpg-ingester configures Docling. Used by both
the pipeline node (``nodes.docling_agent``) and the ``cpg-parse`` CLI
(``parse``) so their behavior can never silently diverge.

Figure extraction/classification and conditional OCR both extend
``build_pdf_pipeline_options`` — keeping the construction here means those
options land in every entry point at once.
"""

from functools import lru_cache

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

# Upscale factor for extracted figure bitmaps. CPG flowcharts/decision trees
# carry fine text; 2x keeps them legible for the downstream figure interpreter
# without exploding image size. Consumed only when extract_figures.
DEFAULT_IMAGES_SCALE = 2.0


def build_pdf_pipeline_options(
    *,
    do_ocr: bool = False,
    extract_figures: bool = True,
    images_scale: float = DEFAULT_IMAGES_SCALE,
) -> PdfPipelineOptions:
    """Build the ``PdfPipelineOptions`` cpg-ingester uses for CPG PDFs.

    ``do_ocr`` defaults to ``False``: most CPGs are born-digital, and OCR adds
    significant latency. Scanned PDFs are handled by a conditional re-parse
    in ``docling_agent``, which calls this with ``do_ocr=True``. When enabled we use
    **RapidOCR** (ONNX, pip-installable, offline — no system binary), with
    ``force_full_page_ocr`` since scanned pages have no text layer to sample.

    ``extract_figures`` (default ``True``) turns on picture-image
    generation and classification so ``docling_agent`` can pull each figure's
    bitmap, class, and provenance out for the figure interpreter.
    It requires the ``picture_classifier`` model (baked into the ingestion
    image); disable it where that model is unavailable.
    """
    options = PdfPipelineOptions(do_ocr=do_ocr)
    if do_ocr:
        options.ocr_options = RapidOcrOptions(force_full_page_ocr=True)
    if extract_figures:
        options.generate_picture_images = True
        options.images_scale = images_scale
        options.do_picture_classification = True
    return options


@lru_cache(maxsize=4)
def _cached_converter(
    do_ocr: bool, extract_figures: bool, images_scale: float
) -> DocumentConverter:
    """Construct (and memoize) a converter for a given option combination.

    Building a converter loads Docling models — seconds of latency and hundreds
    of MB — so the long-lived ingestion service must not rebuild one per request
    (a scanned PDF triggers two parses = two builds). Cached by the small set of
    option combinations cpg-ingester actually uses (OCR on/off × figures on/off).
    Callers **must serialize** ``.convert()`` on the returned instance — Docling's
    converter is not documented thread-safe (see ``docling_agent._convert``).
    """
    options = build_pdf_pipeline_options(
        do_ocr=do_ocr, extract_figures=extract_figures, images_scale=images_scale
    )
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def build_converter(
    *,
    do_ocr: bool = False,
    extract_figures: bool = True,
    images_scale: float = DEFAULT_IMAGES_SCALE,
) -> DocumentConverter:
    """Return a Docling ``DocumentConverter`` configured for CPG PDFs (cached)."""
    return _cached_converter(do_ocr, extract_figures, images_scale)
