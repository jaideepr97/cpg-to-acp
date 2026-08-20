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


def build_pdf_pipeline_options(*, do_ocr: bool = False) -> PdfPipelineOptions:
    """Build the ``PdfPipelineOptions`` cpg-ingester uses for CPG PDFs.

    ``do_ocr`` defaults to ``False``: most CPGs are born-digital, and OCR adds
    significant latency. Scanned PDFs are handled by a conditional re-parse
    (see plan P4), which calls this with ``do_ocr=True``.
    """
    return PdfPipelineOptions(do_ocr=do_ocr)


def build_converter(*, do_ocr: bool = False) -> DocumentConverter:
    """Build a Docling ``DocumentConverter`` configured for CPG PDFs."""
    options = build_pdf_pipeline_options(do_ocr=do_ocr)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
