"""Phase 3 document services: PDF text extraction, span management."""

import html as _html

from django.db import transaction

from .models import TextSpan

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


def extract_markdown_from_pdf(document) -> bool:
    """Convert PDF to Markdown using pdfplumber (no ML models required).

    Populates document.canonical_markdown in-place (and saves).
    Returns True on success. Does NOT replace canonical_text — both coexist.
    Uses layout=True extraction where available to better preserve reading order
    in multi-column documents.
    """
    try:
        import pdfplumber
    except ImportError:
        return False

    if not document.pdf_file:
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
) -> TextSpan:
    """Create a TextSpan; snaps the text snippet from canonical_text."""
    canonical = document.canonical_text or ""
    if not (0 <= start_char < end_char <= len(canonical)):
        raise ValueError("Span offsets must identify text within canonical_text.")
    text = canonical[start_char:end_char]
    span = TextSpan.objects.create(
        document=document,
        start_char=start_char,
        end_char=end_char,
        text=text,
        created_by=created_by,
    )
    if created_by is not None:
        from apps.annotation.services import emit_audit

        emit_audit(
            created_by,
            "span.create",
            "TextSpan",
            span.pk,
            {"start_char": start_char, "end_char": end_char},
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
