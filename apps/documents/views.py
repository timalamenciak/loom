"""Document reader and span management views."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin

from apps.projects.models import Document, ProjectMembership

from .models import TextSpan
from .services import (
    create_span,
    delete_span,
    ensure_canonical_text,
    render_highlighted_text,
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

        spans = TextSpan.objects.filter(document=document).order_by("start_char")
        highlighted = render_highlighted_text(document.canonical_text or "", spans)

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


class SpanCreateView(LoginRequiredMixin, View):
    """Create a TextSpan from char offsets; returns HTMX partial on XHR."""

    def post(self, request, doc_pk):
        document = get_object_or_404(Document, pk=doc_pk)
        _require_member(request, document)

        try:
            start = int(request.POST["start_char"])
            end = int(request.POST["end_char"])
        except (KeyError, ValueError):
            messages.error(request, "Invalid span offsets.")
            return redirect("document-read", doc_pk=doc_pk)

        canonical = document.canonical_text or ""
        if not (0 <= start < end <= len(canonical)):
            messages.error(request, "Offsets out of range.")
            return redirect("document-read", doc_pk=doc_pk)

        span = create_span(document, start, end, created_by=request.user)
        spans = TextSpan.objects.filter(document=document).order_by("start_char")

        if request.headers.get("HX-Request"):
            # span-select.js (annotation surface) wants JSON so it can open the form panel
            if request.headers.get("X-Span-Select") == "true":
                return JsonResponse(
                    {"span_pk": span.pk, "start_char": start, "end_char": end}
                )
            return render(
                request,
                "documents/partials/span_list.html",
                {"spans": spans, "document": document},
            )

        return redirect("document-read", doc_pk=doc_pk)


class SpanDeleteView(LoginRequiredMixin, View):
    def post(self, request, doc_pk, span_pk):
        document = get_object_or_404(Document, pk=doc_pk)
        _require_member(request, document)
        span = get_object_or_404(TextSpan, pk=span_pk, document=document)
        delete_span(span, request.user)
        spans = TextSpan.objects.filter(document=document).order_by("start_char")

        if request.headers.get("HX-Request"):
            return render(
                request,
                "documents/partials/span_list.html",
                {"spans": spans, "document": document},
            )

        return redirect("document-read", doc_pk=doc_pk)
