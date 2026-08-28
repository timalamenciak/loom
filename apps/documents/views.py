"""Document reader and span management views."""

import re
import unicodedata

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import (
    FileResponse,
    Http404,
    HttpResponseBadRequest,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin

from apps.annotation.policies import (
    assignment_is_editable,
    require_editable_assignment,
)
from apps.projects.models import Document, ProjectMembership

from .models import TextSpan
from .services import (
    create_span,
    delete_span,
    ensure_canonical_text,
    render_highlighted_text,
    update_span,
)


def _user_spans(document, user):
    return (
        TextSpan.objects.filter(document=document, created_by=user)
        .prefetch_related("nodes", "edges")
        .order_by("start_char", "created_at")
    )


def _spans_partial_response(request, document, spans):
    """Re-render the surface that issued a span create/update/delete request."""
    if request.GET.get("surface") == "excerpt-bin":
        return render(
            request,
            "annotation/partials/excerpt_bin.html",
            {"spans": spans, "document": document, "can_edit_spans": True},
        )
    return render(
        request,
        "documents/partials/span_list.html",
        {"spans": spans, "document": document, "can_edit_spans": True},
    )


def _require_member(request, document):
    """Raise PermissionDenied if the user is not a member of the document's project."""
    if request.user.is_superuser:
        return
    if not ProjectMembership.objects.filter(
        project=document.project, user=request.user
    ).exists():
        raise PermissionDenied


class DocumentReaderView(LoginRequiredMixin, View):
    """Canonical-text pane + PDF.js viewer; span selection and creation."""

    template_name = "documents/reader.html"

    def get(self, request, doc_pk):
        document = get_object_or_404(Document, pk=doc_pk)
        _require_member(request, document)
        ensure_canonical_text(document)

        assignment = document.assignments.filter(annotator=request.user).first()
        can_edit_spans = bool(assignment and assignment_is_editable(assignment))
        spans = (
            TextSpan.objects.filter(document=document, created_by=request.user)
            .prefetch_related("nodes", "edges")
            .order_by("start_char", "created_at")
        )
        text_spans = spans.filter(text_source="canonical_text")
        highlighted = render_highlighted_text(document.canonical_text or "", text_spans)

        return render(
            request,
            self.template_name,
            {
                "document": document,
                "spans": spans,
                "highlighted_text": mark_safe(highlighted),
                "page_map": document.page_map or [],
                "has_pdf": bool(document.pdf_file),
                "has_text": bool(document.canonical_text),
                "can_edit_spans": can_edit_spans,
            },
        )


@method_decorator(xframe_options_sameorigin, name="dispatch")
class DocumentPdfView(LoginRequiredMixin, View):
    """Permission-checked inline PDF response for embedded readers."""

    def get(self, request, doc_pk):
        document = get_object_or_404(Document, pk=doc_pk)
        _require_member(request, document)
        if not document.pdf_file:
            raise Http404("No PDF is attached to this document.")

        try:
            pdf = document.pdf_file.open("rb")
        except FileNotFoundError as exc:
            raise Http404("PDF file not found.") from exc

        filename = document.pdf_file.name.rsplit("/", 1)[-1]
        response = FileResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response


def _markdown_plain_text(raw_markdown: str) -> str:
    """Convert markdown to approximate plain text matching what the browser renders.

    Used so that text selected in the rendered markdown view can be found even
    when the raw markdown contains inline formatting markers (**, *, ``, etc.)
    that are invisible in the rendered HTML.
    """
    try:
        import html as _html_std

        import markdown as _md

        html_str = _md.markdown(raw_markdown, extensions=["tables", "fenced_code"])
        # Replace each tag with a space so word boundaries between adjacent block
        # elements (e.g. </h2><p>) are preserved in the resulting plain text.
        plain = re.sub(r"<[^>]+>", " ", html_str)
        return _html_std.unescape(plain)
    except Exception:
        # Fallback: strip the most common inline markers without the markdown lib
        text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", raw_markdown, flags=re.DOTALL)
        text = re.sub(r"_{1,2}(.*?)_{1,2}", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
        return text


def _search_canonical(
    needle: str, haystack: str
) -> tuple[int, int] | tuple[None, None]:
    """Find needle in haystack with progressive normalisation.

    Handles typography differences between Marker (LLM-assisted) and pdfplumber:
    ligatures (ﬁ→fi), curly quotes, en/em-dashes, non-breaking spaces, and
    whitespace collapsing.  Returns (start, end) character offsets into the
    ORIGINAL haystack, or (None, None) when no match is found.
    """

    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFKC", s)
        s = s.replace("‘", "'").replace("’", "'")
        s = s.replace("“", '"').replace("”", '"')
        s = s.replace("–", "-").replace("—", "-").replace("−", "-")
        s = s.replace(" ", " ")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    for n, h in [
        (needle.strip(), haystack),
        (re.sub(r"\s+", " ", needle).strip(), haystack),
        (_norm(needle), haystack),
        (_norm(needle), _norm(haystack)),
    ]:
        if not n:
            continue
        idx = h.find(n)
        if idx != -1:
            return idx, idx + len(n)

    return None, None


class SpanCreateView(LoginRequiredMixin, View):
    """Create a TextSpan from char offsets; returns HTMX partial on XHR."""

    def post(self, request, doc_pk):
        document = get_object_or_404(Document, pk=doc_pk)
        require_editable_assignment(document, request.user)

        text_source = request.POST.get("text_source", "canonical_text")
        if text_source not in ("canonical_text", "canonical_markdown", "free_text"):
            text_source = "canonical_text"

        source_text = request.POST.get("source_text", "").strip()
        if text_source == "free_text":
            # Manually typed excerpt — no position in the article. Dummy offsets
            # (0..len) satisfy the DB constraint; span.text is the payload.
            if not source_text:
                return HttpResponseBadRequest("Excerpt text is required.")
            span = create_span(
                document,
                0,
                len(source_text),
                created_by=request.user,
                text_source=text_source,
                text=source_text,
            )
            start, end = 0, len(source_text)
        elif source_text and text_source == "canonical_markdown":
            # Markdown-view selection: the user highlighted rendered HTML, so the
            # selected text won't match the raw markdown (which has ** / ## / etc.).
            # Try a best-effort position search so offsets aren't completely bogus,
            # but ALWAYS create the span — the text content is what matters here.
            plain = _markdown_plain_text(document.canonical_markdown or "")
            start, end = _search_canonical(source_text, plain)
            if start is None:
                # Position unknown; dummy offsets satisfy the DB constraint
                # (start >= 0, end > start).  span.text is still correct.
                start, end = 0, len(source_text)
            span = create_span(
                document,
                start,
                end,
                created_by=request.user,
                text_source=text_source,
                text=source_text,
            )
        elif source_text:
            # Text-search path for canonical_text (used by document-reader view).
            start, end = _search_canonical(source_text, document.canonical_text or "")
            if start is None:
                if request.headers.get("X-Span-Select") == "true":
                    return JsonResponse(
                        {"error": "passage_not_found"},
                        status=422,
                    )
                messages.error(
                    request,
                    "Passage not found. Try selecting a more distinctive phrase.",
                )
                return redirect("document-read", doc_pk=doc_pk)
            span = create_span(
                document, start, end, created_by=request.user, text_source=text_source
            )
        else:
            # Offset path: used for text-view selections (precomputed by JS).
            text_source = "canonical_text"
            canonical = document.canonical_text or ""
            try:
                start = int(request.POST["start_char"])
                end = int(request.POST["end_char"])
            except (KeyError, ValueError):
                messages.error(request, "Invalid span offsets.")
                return redirect("document-read", doc_pk=doc_pk)

            if not (0 <= start < end <= len(canonical)):
                messages.error(request, "Offsets out of range.")
                return redirect("document-read", doc_pk=doc_pk)
            span = create_span(
                document, start, end, created_by=request.user, text_source=text_source
            )

        spans = _user_spans(document, request.user)

        if request.headers.get("HX-Request"):
            # The span-select flow wants JSON so it can refresh its excerpt bin
            # and mark the new range client-side.
            if request.headers.get("X-Span-Select") == "true":
                return JsonResponse(
                    {
                        "span_pk": span.pk,
                        "start_char": start,
                        "end_char": end,
                        "excerpt_bin_html": render_to_string(
                            "annotation/partials/excerpt_bin.html",
                            {
                                "spans": spans,
                                "document": document,
                                "can_edit_spans": True,
                            },
                            request=request,
                        ),
                    }
                )
            return _spans_partial_response(request, document, spans)

        return redirect("document-read", doc_pk=doc_pk)


class SpanDeleteView(LoginRequiredMixin, View):
    def post(self, request, doc_pk, span_pk):
        document = get_object_or_404(Document, pk=doc_pk)
        require_editable_assignment(document, request.user)
        span = get_object_or_404(
            TextSpan,
            pk=span_pk,
            document=document,
            created_by=request.user,
        )
        delete_span(span, request.user)
        spans = _user_spans(document, request.user)

        if request.headers.get("HX-Request"):
            return _spans_partial_response(request, document, spans)

        return redirect("document-read", doc_pk=doc_pk)


class SpanUpdateView(LoginRequiredMixin, View):
    """Edit a span's snippet text (offsets and highlight are left in place)."""

    def post(self, request, doc_pk, span_pk):
        document = get_object_or_404(Document, pk=doc_pk)
        require_editable_assignment(document, request.user)
        span = get_object_or_404(
            TextSpan,
            pk=span_pk,
            document=document,
            created_by=request.user,
        )

        text = request.POST.get("text", "").strip()
        if not text:
            if request.headers.get("HX-Request"):
                return HttpResponseBadRequest("Excerpt text is required.")
            messages.error(request, "Excerpt text is required.")
            return redirect("document-read", doc_pk=doc_pk)

        if (
            span.text_source != "free_text"
            and len(text) != span.end_char - span.start_char
        ):
            error = (
                "Edited text must be the same length as the original highlight "
                f"({span.end_char - span.start_char} characters). Delete this "
                "excerpt and re-select the passage if you need different text."
            )
            if request.headers.get("HX-Request"):
                return HttpResponseBadRequest(error)
            messages.error(request, error)
            return redirect("document-read", doc_pk=doc_pk)

        update_span(span, text, request.user)
        spans = _user_spans(document, request.user)

        if request.headers.get("HX-Request"):
            return _spans_partial_response(request, document, spans)

        return redirect("document-read", doc_pk=doc_pk)
