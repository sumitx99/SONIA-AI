# app/docling_utils.py

import logging
import os
from functools import lru_cache
from io import BytesIO

import pymupdf

logger = logging.getLogger(__name__)


def docling_enabled() -> bool:
    # "pymupdf" skips Docling entirely (no torch in memory) for small servers such as
    # Render's free plan; "docling" (default) uses it, falling back to PyMuPDF on failure.
    return os.getenv("PDF_PARSER", "docling").strip().lower() == "docling"


@lru_cache(maxsize=1)
def _converter():
    # Imported lazily: Docling loads layout/table models, which is slow and only needed on upload.
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions()
    # OCR is only needed for scanned PDFs and is by far the slowest step; opt in via .env.
    options.do_ocr = os.getenv("DOCLING_OCR", "false").strip().lower() == "true"
    options.do_table_structure = True
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def _extract_with_pymupdf(file_bytes: bytes) -> str:
    """Plain-text fallback: no layout or tables, but every page's words, in reading order."""
    with pymupdf.open(stream=file_bytes, filetype="pdf") as document:
        return "\n\n".join(page.get_text("text", sort=True).strip() for page in document).strip()


def process_pdf_with_docling(file_bytes: bytes, filename: str) -> str:
    """
    Converts a PDF to layout-aware Markdown (headings, lists, tables) with Docling, locally.
    Falls back to PyMuPDF text if Docling fails, so uploads still work; returns "" only if
    neither finds any text (e.g. a scanned PDF without DOCLING_OCR=true).
    """
    if not docling_enabled():
        return _extract_with_pymupdf(file_bytes)
    try:
        from docling.datamodel.base_models import DocumentStream

        # Read from memory: the user's filename is only a label, never a path.
        source = DocumentStream(name=os.path.basename(filename) or "document.pdf", stream=BytesIO(file_bytes))
        content = _converter().convert(source).document.export_to_markdown().strip()
        if content:
            return content
        logger.warning("Docling found no text in %s; using PyMuPDF text", filename)
    except Exception:
        logger.exception("Docling failed for %s; using PyMuPDF text", filename)

    try:
        return _extract_with_pymupdf(file_bytes)
    except Exception:
        logger.exception("PyMuPDF could not read %s", filename)
        return ""
