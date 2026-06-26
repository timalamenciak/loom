"""Phase 3 document services: PDF text extraction, span management."""

import html as _html

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
    if document.abstract and document.canonical_text.strip() == document.abstract.strip():
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


def create_span(
    document,
    start_char: int,
    end_char: int,
    created_by=None,
) -> TextSpan:
    """Create a TextSpan; snaps the text snippet from canonical_text."""
    canonical = document.canonical_text or ""
    text = canonical[start_char:end_char]
    return TextSpan.objects.create(
        document=document,
        start_char=start_char,
        end_char=end_char,
        text=text,
        created_by=created_by,
    )


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def render_highlighted_text(canonical_text: str, spans) -> str:
    """Return HTML with <mark> tags injected around each span region.

    Uses an event-sweep so overlapping spans close before opening at the
    same boundary, preventing malformed nesting.
    """
    if not canonical_text:
        return ""

    # (char_pos, sort_key, html_fragment)
    #   sort_key 0 = close, 1 = open  →  closes are emitted before opens at the same pos
    events: list[tuple] = []
    for span in spans:
        s, e = span.start_char, span.end_char
        if s < 0 or e <= s or s > len(canonical_text):
            continue
        e = min(e, len(canonical_text))
        events.append(
            (
                s,
                1,
                (
                    f'<mark class="span-highlight" data-span-pk="{span.pk}"'
                    f' title="{_html.escape(span.text[:80])}"'
                    f' data-href="#span-{span.pk}">'
                ),
            )
        )
        events.append((e, 0, "</mark>"))

    events.sort(key=lambda ev: (ev[0], ev[1]))

    parts: list[str] = []
    pos = 0
    for char_pos, _, tag in events:
        if char_pos > pos:
            parts.append(_html.escape(canonical_text[pos:char_pos]))
        parts.append(tag)
        pos = max(pos, char_pos)

    if pos < len(canonical_text):
        parts.append(_html.escape(canonical_text[pos:]))

    return "".join(parts)
