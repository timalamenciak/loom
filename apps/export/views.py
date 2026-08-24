"""
Export views: YAML/Excel download, validation report, bulk import (upload,
preview, apply).
"""

from __future__ import annotations

import hashlib

import yaml
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps.annotation.models import CausalGraph
from apps.annotation.policies import require_import_access
from apps.export.graph_import import (
    ImportParseError,
    apply_import_plan,
    build_import_plan,
    render_plan_text,
)
from apps.export.import_excel import parse_xlsx_import, write_graph_xlsx
from apps.export.import_store import discard_plan, load_plan, stash_plan
from apps.export.import_yaml import parse_yaml_import
from apps.export.renderers import render_fcm, render_rosetta
from apps.export.serializer import build_provenance, serialize_graph
from apps.export.validators import validate_graph_data
from apps.projects.upload_validation import (
    UploadValidationError,
    validate_graph_import_upload,
)
from apps.schemas.schema_engine import get_schema_view


def _require_access(request, graph):
    project = graph.document.project
    if request.user.is_superuser:
        return
    if not project.memberships.filter(user=request.user).exists():
        raise Http404


def _load_graph(graph_pk):
    return get_object_or_404(
        CausalGraph.objects.select_related(
            "document__project", "schema_version", "ontology_snapshot"
        ),
        pk=graph_pk,
    )


def _parse_import_upload(upload) -> tuple[list[dict], list[dict], str]:
    """Return (node_rows, edge_rows, format) for an uploaded import file."""
    name = (upload.name or "").lower()
    if name.endswith(".xlsx"):
        node_rows, edge_rows = parse_xlsx_import(upload)
        return node_rows, edge_rows, "xlsx"
    if name.endswith((".yaml", ".yml")):
        node_rows, edge_rows = parse_yaml_import(upload)
        return node_rows, edge_rows, "yaml"
    raise ImportParseError("Import files must be .xlsx, .yaml, or .yml.")


def _export_data(graph) -> tuple[dict, str, str]:
    """Return (data_dict, final_yaml, sha256) for a graph."""
    data = serialize_graph(graph)
    pre_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=True)
    prov = build_provenance(graph, pre_yaml.encode())
    data["provenance"] = prov
    final_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return data, final_yaml, prov["export_sha256"]


class ExportGraphView(LoginRequiredMixin, View):
    """Show export detail page or download the YAML file."""

    def get(self, request, graph_pk):
        graph = get_object_or_404(
            CausalGraph.objects.select_related(
                "document__project", "schema_version", "ontology_snapshot"
            ),
            pk=graph_pk,
        )
        _require_access(request, graph)

        data, final_yaml, sha256 = _export_data(graph)

        is_valid, validation_messages = validate_graph_data(
            data, graph.schema_version.linkml_yaml
        )

        if request.GET.get("download"):
            if not is_valid:
                return HttpResponse(
                    "Validation errors found:\n" + "\n".join(validation_messages),
                    content_type="text/plain",
                    status=422,
                )
            resp = HttpResponse(final_yaml, content_type="application/x-yaml")
            resp["Content-Disposition"] = (
                f'attachment; filename="graph-{graph_pk}.yaml"'
            )
            return resp
        schema_yaml = graph.schema_version.linkml_yaml
        rosetta = render_rosetta(data, schema_yaml)
        fcm = render_fcm(data, schema_yaml)

        return render(
            request,
            "export/export_detail.html",
            {
                "graph": graph,
                "document": graph.document,
                "project": graph.document.project,
                "data": data,
                "rosetta": rosetta,
                "fcm": fcm,
                "yaml_preview": final_yaml,
                "sha256": sha256,
                "is_valid": is_valid,
                "validation_messages": validation_messages,
            },
        )


class ValidateGraphView(LoginRequiredMixin, View):
    """Run linkml-validate and show the report."""

    def get(self, request, graph_pk):
        graph = get_object_or_404(
            CausalGraph.objects.select_related(
                "document__project", "schema_version", "ontology_snapshot"
            ),
            pk=graph_pk,
        )
        _require_access(request, graph)

        data, _yaml, _sha = _export_data(graph)
        is_valid, messages = validate_graph_data(data, graph.schema_version.linkml_yaml)

        return render(
            request,
            "export/validate_result.html",
            {
                "graph": graph,
                "document": graph.document,
                "project": graph.document.project,
                "is_valid": is_valid,
                "messages": messages,
            },
        )


class ExportExcelView(LoginRequiredMixin, View):
    """Download the current graph (or a blank template with ?blank=1) as .xlsx."""

    def get(self, request, graph_pk):
        graph = _load_graph(graph_pk)
        _require_access(request, graph)

        blank = bool(request.GET.get("blank"))
        content = write_graph_xlsx(graph, blank=blank)
        suffix = "template" if blank else str(graph_pk)
        resp = HttpResponse(
            content,
            content_type=(
                "application/vnd.openxmlformats-officedocument" ".spreadsheetml.sheet"
            ),
        )
        resp["Content-Disposition"] = f'attachment; filename="graph-{suffix}.xlsx"'
        return resp


class ImportUploadView(LoginRequiredMixin, View):
    """Upload a graph import file: validate, diff, and stash a preview plan.

    No writes happen here — build_import_plan() only reads the graph and
    the uploaded file. The plan is stashed (import_store.stash_plan) and the
    user is sent to ImportPreviewView to review it before anything commits.
    """

    def get(self, request, graph_pk):
        graph = _load_graph(graph_pk)
        require_import_access(graph.document, request.user)
        return render(
            request,
            "export/import_upload.html",
            {
                "graph": graph,
                "document": graph.document,
                "project": graph.document.project,
            },
        )

    def post(self, request, graph_pk):
        graph = _load_graph(graph_pk)
        require_import_access(graph.document, request.user)

        full_sync = bool(request.POST.get("full_sync"))
        context = {
            "graph": graph,
            "document": graph.document,
            "project": graph.document.project,
            "full_sync": full_sync,
        }

        upload = request.FILES.get("import_file")
        if upload is None:
            context["error"] = "Choose a file to upload."
            return render(request, "export/import_upload.html", context)

        try:
            validate_graph_import_upload(upload, upload.name)
            upload.seek(0)
            node_rows, edge_rows, import_format = _parse_import_upload(upload)
        except (UploadValidationError, ImportParseError) as exc:
            context["error"] = str(exc)
            return render(request, "export/import_upload.html", context)

        upload.seek(0)
        source_sha256 = hashlib.sha256(upload.read()).hexdigest()

        schema_view = get_schema_view(graph.schema_version, graph.document.project)
        plan = build_import_plan(
            graph,
            node_rows,
            edge_rows,
            schema_view=schema_view,
            full_sync=full_sync,
            source_sha256=source_sha256,
            format=import_format,
            uploaded_by_id=request.user.pk,
        )
        token = stash_plan(plan)
        preview_url = reverse("import-graph-preview", args=[graph.pk])
        return redirect(f"{preview_url}?token={token}")


class ImportPreviewView(LoginRequiredMixin, View):
    """Show the diff report for a stashed import plan. No writes happen here."""

    def get(self, request, graph_pk):
        graph = _load_graph(graph_pk)
        require_import_access(graph.document, request.user)

        plan = load_plan(request.GET.get("token", ""))
        if plan is None or plan.graph_id != graph.pk:
            messages.warning(request, "Your import preview expired. Please re-upload.")
            return redirect("import-graph", graph_pk=graph.pk)

        return render(
            request,
            "export/import_preview.html",
            {
                "graph": graph,
                "document": graph.document,
                "project": graph.document.project,
                "plan": plan,
                "counts": plan.counts(),
                "report": render_plan_text(plan),
                "token": request.GET.get("token", ""),
            },
        )


class ImportApplyView(LoginRequiredMixin, View):
    """Commit a previewed import plan."""

    def post(self, request, graph_pk):
        graph = _load_graph(graph_pk)
        _assignment, is_admin = require_import_access(graph.document, request.user)

        token = request.POST.get("token", "")
        plan = load_plan(token)
        if plan is None or plan.graph_id != graph.pk:
            messages.warning(request, "Your import preview expired. Please re-upload.")
            return redirect("import-graph", graph_pk=graph.pk)
        if not is_admin and plan.uploaded_by_id != request.user.pk:
            raise PermissionDenied("This import was previewed by a different user.")

        # Claim the token before applying: a double-submitted Apply (double
        # click, retried request) then finds the token already gone and
        # takes the "expired" branch above instead of racing a second
        # apply_import_plan() call against the first. The IntegrityError
        # guard below is a backstop for the narrow window where both
        # requests load the plan before either discards it.
        discard_plan(token)
        try:
            counts = apply_import_plan(plan, request.user)
        except IntegrityError:
            messages.warning(
                request,
                "This import may already have been applied (duplicate "
                "submission detected). Check the graph below before "
                "re-uploading.",
            )
            return redirect("export-graph", graph_pk=graph.pk)
        messages.success(
            request,
            f"Import applied: {counts['nodes_create']} node(s) created, "
            f"{counts['nodes_update']} updated, {counts['edges_create']} edge(s) created, "
            f"{counts['edges_update']} updated"
            + (
                f", {counts['nodes_would_delete']} node(s) and {counts['edges_would_delete']} "
                "edge(s) deleted (full sync)."
                if plan.full_sync
                else "."
            ),
        )
        return redirect("export-graph", graph_pk=graph.pk)
