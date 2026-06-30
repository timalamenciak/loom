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
from .wikidata_search import search as wikidata_search


def _snapshot_prefixes(snapshot) -> set[str]:
    if snapshot is None:
        return set()
    prefixes = set((snapshot.source_versions or {}).keys())
    prefixes.update(snapshot.releases.values_list("prefix", flat=True))
    if not prefixes:
        prefixes.update(snapshot.terms.values_list("prefix", flat=True).distinct())
    return prefixes


def _merge_wikidata(request, results: list[dict], q: str, limit: int) -> list[dict]:
    """Append Wikidata live results when the caller requests it.

    Triggered by ``?wikidata_live=1``; ``?root_qid=`` is optional.  Results
    whose CURIE already appears in *results* are silently dropped so local
    terms take precedence.

    Wikidata results carry ``"source": "wikidata"`` so the frontend can label
    them distinctly.  Any failure (network, timeout, 429, unexpected exception)
    is silently swallowed — annotation work must never block on Wikidata being
    reachable.
    """
    if request.GET.get("wikidata_live") != "1":
        return results
    root_qid = request.GET.get("root_qid") or None
    try:
        wd = wikidata_search(q, root_qid=root_qid, limit=limit)
    except Exception:
        return results
    seen = {r["curie"] for r in results}
    for item in wd:
        if item["curie"] not in seen:
            results.append(
                {
                    "curie": item["curie"],
                    "prefix": item.get("prefix") or "WD",
                    "label": item["label"],
                    "definition": item.get("description", ""),
                    "synonyms": [],
                    "source": "wikidata",
                }
            )
            seen.add(item["curie"])
    return results


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
                "prefix": t.prefix,
                "label": t.label,
                "definition": (t.definition or "")[:200],
                "synonyms": (t.synonyms or [])[:4],
            }
            for t in terms
        ]
        results = _merge_wikidata(request, results, q, limit)
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

        project_snapshot = project.ontology_snapshot
        snapshot = project_snapshot
        graph_pk = request.GET.get("graph")
        graph = None
        graph_snapshot = None
        if graph_pk:
            graph = get_object_or_404(
                CausalGraph, pk=graph_pk, document__project=project
            )
            graph_snapshot = graph.ontology_snapshot
            snapshot = graph_snapshot or snapshot
        # Fall back to the site-wide active snapshot so search works out of
        # the box when no per-project snapshot has been pinned yet.
        if snapshot is None:
            from .models import OntologySnapshot as _Snap

            snapshot = _Snap.get_active()

        q = request.GET.get("q", "").strip()
        if len(q) < 2:
            return JsonResponse({"results": []})
        try:
            limit = min(max(int(request.GET.get("limit", 20)), 1), 50)
        except ValueError:
            limit = 20
        requested = {
            prefix.strip()
            for prefix in request.GET.get("prefixes", "").split(",")
            if prefix.strip()
        }

        if requested and graph_snapshot and project_snapshot:
            graph_prefixes = _snapshot_prefixes(graph_snapshot)
            project_prefixes = _snapshot_prefixes(project_snapshot)
            missing_from_graph = requested - graph_prefixes
            if missing_from_graph & project_prefixes:
                snapshot = project_snapshot

        # Local DB search — only possible when a snapshot exists.
        results: list[dict] = []
        if snapshot is not None:
            if graph and snapshot:
                allowed_prefixes = _snapshot_prefixes(snapshot)
            else:
                selected_names = set(project.ontology_names or [])
                allowed_prefixes = {
                    entry["prefix"]
                    for entry in ontology_entries()
                    if entry["name"] in selected_names
                }
            prefixes = (
                sorted(allowed_prefixes & requested)
                if requested
                else sorted(allowed_prefixes)
            )
            # Only query DB when the prefix intersection is non-empty (or no
            # specific prefixes were requested).
            if prefixes or not requested:
                terms = search_terms(
                    q, prefixes=prefixes or None, snapshot=snapshot, limit=limit
                )
                results = [
                    {
                        "curie": term.curie,
                        "prefix": term.prefix,
                        "label": term.label,
                        "definition": (term.definition or "")[:200],
                        "synonyms": (term.synonyms or [])[:4],
                    }
                    for term in terms
                ]

        # Live lookup (Wikidata etc.) — always attempted when caller requests it,
        # even when the local snapshot is absent or yields nothing.
        results = _merge_wikidata(request, results, q, limit)
        return JsonResponse({"results": results})
