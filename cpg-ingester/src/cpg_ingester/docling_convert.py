"""Shared Docling ``DocumentConverter`` construction.

Single source of truth for how cpg-ingester configures Docling. Used by both
the pipeline node (``nodes.docling_agent``) and the ``cpg-parse`` CLI
(``parse``) so their behavior can never silently diverge.

Rationale and roadmap: ``working/RHAIENG-6461-docling-review/``. Figure
extraction/classification (P3) and conditional OCR (P4) will extend
``build_pdf_pipeline_options`` — keeping the construction here means those
options land in every entry point at once.
"""

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

# Upscale factor for extracted figure bitmaps. CPG flowcharts/decision trees
# carry fine text; 2x keeps them legible for the downstream figure interpreter
# (plan P5) without exploding image size. Consumed only when extract_figures.
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
    (see plan P4), which calls this with ``do_ocr=True``.

    ``extract_figures`` (default ``True``, plan P3) turns on picture-image
    generation and classification so ``docling_agent`` can pull each figure's
    bitmap, class, and provenance out for the figure interpreter (plan P5).
    It requires the ``picture_classifier`` model (baked into the ingestion
    image); disable it where that model is unavailable.
    """
    options = PdfPipelineOptions(do_ocr=do_ocr)
    if extract_figures:
        options.generate_picture_images = True
        options.images_scale = images_scale
        options.do_picture_classification = True
    return options


def build_converter(
    *,
    do_ocr: bool = False,
    extract_figures: bool = True,
    images_scale: float = DEFAULT_IMAGES_SCALE,
) -> DocumentConverter:
    """Build a Docling ``DocumentConverter`` configured for CPG PDFs."""
    options = build_pdf_pipeline_options(
        do_ocr=do_ocr, extract_figures=extract_figures, images_scale=images_scale
    )
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
