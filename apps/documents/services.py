"""Phase 3 document services: PDF text extraction, span management."""

import html as _html
import logging as _logging
import os as _os
from pathlib import Path as _Path

from django.conf import settings as _django_settings
from django.db import transaction

from .models import TextSpan

_logger = _logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def extract_text_from_pdf(document) -> bool:
    """Extract canonical text from document.pdf_file using pdfplumber.

    Populates document.canonical_text and document.page_map in-place (and saves).
    Returns True on success, False if the document has no PDF or extraction fails.
    """
    try:
        import pdfplumber
    except ImportError:
        return False

    if not document.pdf_file:
        return False

    pages_text: list[str] = []
    page_map: list[dict] = []
    char_offset = 0

    try:
        with pdfplumber.open(document.pdf_file.path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                page_map.append(
                    {
                        "page": page_num,
                        "start_char": char_offset,
                        "end_char": char_offset + len(text),
                    }
                )
                pages_text.append(text)
                char_offset += len(text) + 1  # +1 for inter-page newline
    except Exception:
        return False

    document.canonical_text = "\n".join(pages_text)
    document.page_map = page_map
    document.save(update_fields=["canonical_text", "page_map"])
    return True


def pdf_text_needs_extraction(document) -> bool:
    """Return True when a PDF is attached but full-text extraction is not done."""
    if not document.pdf_file:
        return False
    if not document.canonical_text:
        return True
    if (
        document.abstract
        and document.canonical_text.strip() == document.abstract.strip()
    ):
        return not bool(document.page_map)
    return False


def set_abstract_as_canonical(document) -> bool:
    """Use the RIS abstract as canonical text for PDF-less records."""
    if not document.abstract:
        return False
    document.canonical_text = document.abstract
    document.page_map = []
    document.save(update_fields=["canonical_text", "page_map"])
    return True


def _extract_markdown_with_marker(pdf_path: str) -> str | None:
    """Convert a PDF to Markdown using marker-pdf (>=1.0).

    Respects MARKER_LLM_* settings for an optional OpenAI-compatible LLM boost
    (e.g. a local Qwen endpoint). Returns the Markdown string, or None when
    marker-pdf is not installed or conversion fails.

    LLM service env vars (OPENAI_BASE_URL, OPENAI_API_KEY) are set temporarily
    around the call and restored on exit so they don't leak to other threads.
    Marker 1.x passes these to its internal litellm-backed OpenAI service.
    """
    # DISABLED: Marker runs off-process on a separate GPU machine.
    # Use helper-scripts/marker_convert.py to produce .md sidecars, then run
    # python manage.py extract_markdown to ingest them.
    #
    # TO RE-ENABLE in-process Marker:
    #   1. Delete the "return None" line immediately below.
    #   2. Un-comment the MARKER_* settings block in loom/settings/base.py.
    #   3. Un-comment the pip install step in Dockerfile.
    return None

    # --- original in-process body (preserved for re-enable) ---
    try:
        from marker.config.parser import ConfigParser
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
    except ImportError:
        _logger.warning(
            "MARKER_ENABLED=True but marker-pdf is not installed. "
            "Run: pip install 'loom[marker]'"
        )
        return None
    except Exception:
        _logger.exception("marker-pdf import failed unexpectedly (version mismatch?)")
        return None

    config: dict = {"force_ocr": False}
    env_overrides: dict[str, str] = {}

    if getattr(_django_settings, "MARKER_LLM_ENABLED", False) and getattr(
        _django_settings, "MARKER_LLM_BASE_URL", ""
    ):
        config["use_llm"] = True
        config["default_llm_service"] = "marker.services.openai.OpenAIService"
        env_overrides["OPENAI_BASE_URL"] = _django_settings.MARKER_LLM_BASE_URL
        env_overrides["OPENAI_API_KEY"] = _django_settings.MARKER_LLM_API_KEY or "nokey"
        if model := getattr(_django_settings, "MARKER_LLM_MODEL", ""):
            config["openai_model"] = model

    old_env = {k: _os.environ.get(k) for k in env_overrides}
    try:
        _os.environ.update(env_overrides)
        config_parser = ConfigParser(config)
        converter = PdfConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=create_model_dict(),
        )
        rendered = converter(pdf_path)
        return rendered.markdown
    except Exception:
        _logger.exception("marker-pdf conversion failed for %s", pdf_path)
        return None
    finally:
        for k, v in old_env.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v


def extract_markdown_from_pdf(document) -> bool:
    """Convert PDF to Markdown, saving to document.canonical_markdown.

    Checks for a .md sidecar alongside the PDF first (produced by
    helper-scripts/marker_convert.py on a separate machine). Falls back to
    pdfplumber for basic page-by-page text. Does NOT replace canonical_text.
    Returns True on success.
    """
    if not document.pdf_file:
        return False

    # Sidecar produced by helper-scripts/marker_convert.py: same stem, .md ext.
    sidecar = _Path(document.pdf_file.path).with_suffix(".md")
    if sidecar.exists():
        document.canonical_markdown = sidecar.read_text(encoding="utf-8")
        document.save(update_fields=["canonical_markdown"])
        return True

    # TO RE-ENABLE in-process Marker: un-comment the block below and follow
    # the instructions at the top of _extract_markdown_with_marker().
    #
    # if getattr(_django_settings, "MARKER_ENABLED", False):
    #     markdown = _extract_markdown_with_marker(document.pdf_file.path)
    #     if markdown is not None:
    #         document.canonical_markdown = markdown
    #         document.save(update_fields=["canonical_markdown"])
    #         return True
    #     _logger.warning(
    #         "Marker extraction returned nothing for document %s; falling back to pdfplumber.",
    #         document.pk,
    #     )

    # pdfplumber fallback
    try:
        import pdfplumber
    except ImportError:
        return False

    try:
        with pdfplumber.open(document.pdf_file.path) as pdf:
            sections = []
            for i, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text(layout=True) or ""
                except TypeError:
                    text = page.extract_text() or ""
                text = text.strip()
                if text:
                    sections.append(f"## Page {i}\n\n{text}")
            document.canonical_markdown = "\n\n---\n\n".join(sections)
            document.save(update_fields=["canonical_markdown"])
            return True
    except Exception:
        return False


def ensure_canonical_text(document) -> bool:
    """Guarantee canonical_text is populated; return True if text is now available."""
    if pdf_text_needs_extraction(document) and extract_text_from_pdf(document):
        return True
    if document.canonical_text:
        return True
    return set_abstract_as_canonical(document)


# ---------------------------------------------------------------------------
# Span management
# ---------------------------------------------------------------------------


@transaction.atomic
def create_span(
    document,
    start_char: int,
    end_char: int,
    created_by=None,
    text_source: str = "canonical_text",
    text: str | None = None,
) -> TextSpan:
    """Create a TextSpan; snaps the text snippet from the specified text source.

    Pass ``text`` explicitly when the offsets are into a derived representation
    (e.g. plain text extracted from markdown) rather than the raw text source.
    """
    if text is None:
        if text_source == "canonical_markdown":
            canonical = document.canonical_markdown or ""
        else:
            canonical = document.canonical_text or ""
        if not (0 <= start_char < end_char <= len(canonical)):
            raise ValueError(f"Span offsets must identify text within {text_source}.")
        text = canonical[start_char:end_char]
    span = TextSpan.objects.create(
        document=document,
        start_char=start_char,
        end_char=end_char,
        text=text,
        text_source=text_source,
        created_by=created_by,
    )
    if created_by is not None:
        from apps.annotation.services import emit_audit

        emit_audit(
            created_by,
            "span.create",
            "TextSpan",
            span.pk,
            {
                "start_char": start_char,
                "end_char": end_char,
                "text_source": text_source,
            },
        )
    return span


@transaction.atomic
def delete_span(span: TextSpan, actor) -> None:
    """Delete a span through the audited document service boundary."""
    from apps.annotation.services import emit_audit

    emit_audit(actor, "span.delete", "TextSpan", span.pk)
    span.delete()


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def render_highlighted_text(canonical_text: str, spans) -> str:
    """Return escaped HTML with valid, non-nested marks for span regions."""
    if not canonical_text:
        return ""

    valid_spans: list[tuple[int, int, object]] = []
    boundaries = {0, len(canonical_text)}
    for span in spans:
        s, e = span.start_char, span.end_char
        if s < 0 or e <= s or s > len(canonical_text):
            continue
        e = min(e, len(canonical_text))
        valid_spans.append((s, e, span))
        boundaries.update((s, e))

    parts: list[str] = []
    ordered = sorted(boundaries)
    for start, end in zip(ordered, ordered[1:]):
        if end <= start:
            continue
        text = _html.escape(canonical_text[start:end])
        active = [span for s, e, span in valid_spans if s < end and e > start]
        if not active:
            parts.append(text)
            continue
        primary = active[0]
        span_ids = ",".join(str(span.pk) for span in active)
        titles = " | ".join(span.text[:80] for span in active)
        parts.append(
            f'<mark class="span-highlight" data-span-pk="{primary.pk}"'
            f' data-span-pks="{_html.escape(span_ids, quote=True)}"'
            f' title="{_html.escape(titles, quote=True)}"'
            f' data-href="#span-{primary.pk}">{text}</mark>'
        )

    return "".join(parts)
