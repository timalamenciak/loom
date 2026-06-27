"""Ontology search API — JSON endpoint consumed by ontology-autocomplete.js."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from apps.annotation.models import CausalGraph
from apps.projects.models import Project, ProjectMembership

from .loaders import ontology_entries
from .services import search_terms


class OntologySearchView(LoginRequiredMixin, View):
    """GET /ontology/search/?q=<term>&prefixes=NCBITaxon,ENVO&limit=20"""

    def get(self, request):
        q = request.GET.get("q", "").strip()
        raw_prefixes = request.GET.get("prefixes", "").strip()
        prefixes = [p.strip() for p in raw_prefixes.split(",") if p.strip()] or None
        try:
            limit = min(max(int(request.GET.get("limit", 20)), 1), 50)
        except (TypeError, ValueError):
            limit = 20

        if len(q) < 2:
            return JsonResponse({"results": []})

        terms = search_terms(q, prefixes=prefixes, limit=limit)
        results = [
            {
                "curie": t.curie,
                "label": t.label,
                "definition": (t.definition or "")[:200],
                "synonyms": (t.synonyms or [])[:4],
            }
            for t in terms
        ]
        return JsonResponse({"results": results})


class ProjectOntologySearchView(LoginRequiredMixin, View):
    """Search the ontology snapshot pinned by this project or one of its graphs."""

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        if (
            not request.user.is_superuser
            and not ProjectMembership.objects.filter(
                project=project, user=request.user
            ).exists()
        ):
            raise PermissionDenied

        snapshot = project.ontology_snapshot
        graph_pk = request.GET.get("graph")
        graph = None
        if graph_pk:
            graph = get_object_or_404(
                CausalGraph, pk=graph_pk, document__project=project
            )
            snapshot = graph.ontology_snapshot or snapshot

        q = request.GET.get("q", "").strip()
        if len(q) < 2 or snapshot is None:
            return JsonResponse({"results": []})
        try:
            limit = min(max(int(request.GET.get("limit", 20)), 1), 50)
        except ValueError:
            limit = 20

        if graph and snapshot:
            allowed_prefixes = set((snapshot.source_versions or {}).keys())
            if not allowed_prefixes:
                allowed_prefixes = set(
                    snapshot.releases.values_list("prefix", flat=True)
                )
        else:
            selected_names = set(project.ontology_names or [])
            allowed_prefixes = {
                entry["prefix"]
                for entry in ontology_entries()
                if entry["name"] in selected_names
            }
        requested = {
            prefix.strip()
            for prefix in request.GET.get("prefixes", "").split(",")
            if prefix.strip()
        }
        prefixes = (
            sorted(allowed_prefixes & requested)
            if requested
            else sorted(allowed_prefixes)
        )
        if requested and not prefixes:
            return JsonResponse({"results": []})

        terms = search_terms(
            q, prefixes=prefixes or None, snapshot=snapshot, limit=limit
        )
        return JsonResponse(
            {
                "results": [
                    {
                        "curie": term.curie,
                        "label": term.label,
                        "definition": (term.definition or "")[:200],
                        "synonyms": (term.synonyms or [])[:4],
                    }
                    for term in terms
                ]
            }
        )
