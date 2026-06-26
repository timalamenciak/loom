"""
Export views: YAML download, validation report.
"""

from __future__ import annotations

import yaml
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from apps.annotation.models import CausalGraph
from apps.export.renderers import render_fcm, render_rosetta
from apps.export.serializer import build_provenance, serialize_graph
from apps.export.validators import validate_graph_data


def _require_access(request, graph):
    project = graph.document.project
    if not project.memberships.filter(user=request.user).exists():
        raise Http404


def _ontology_snapshot_id(graph) -> str:
    try:
        from apps.ontology.models import OntologyTerm
        count = OntologyTerm.objects.count()
        return f"local-{count}"
    except Exception:
        return "none"


def _export_data(graph) -> tuple[dict, str, str]:
    """Return (data_dict, final_yaml, sha256) for a graph."""
    data = serialize_graph(graph)
    pre_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=True)
    prov = build_provenance(
        graph,
        pre_yaml.encode(),
        ontology_snapshot_id=_ontology_snapshot_id(graph),
    )
    data["provenance"] = prov
    final_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return data, final_yaml, prov["export_sha256"]


class ExportGraphView(LoginRequiredMixin, View):
    """Show export detail page or download the YAML file."""

    def get(self, request, graph_pk):
        graph = get_object_or_404(
            CausalGraph.objects.select_related("document__project", "schema_version"),
            pk=graph_pk,
        )
        _require_access(request, graph)

        data, final_yaml, sha256 = _export_data(graph)

        if request.GET.get("download"):
            resp = HttpResponse(final_yaml, content_type="application/x-yaml")
            resp["Content-Disposition"] = f'attachment; filename="graph-{graph_pk}.yaml"'
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
            },
        )


class ValidateGraphView(LoginRequiredMixin, View):
    """Run linkml-validate and show the report."""

    def get(self, request, graph_pk):
        graph = get_object_or_404(
            CausalGraph.objects.select_related("document__project", "schema_version"),
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
