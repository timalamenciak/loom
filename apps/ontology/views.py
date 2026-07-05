"""Ontology search API — JSON endpoint consumed by ontology-autocomplete.js."""

import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from apps.annotation.models import CausalGraph
from apps.projects.models import Project, ProjectMembership

from .loaders import ontology_entries
from .models import OntologyTermSuggestion
from .services import search_terms, terms_by_curies
from .wikidata_search import WikidataUnavailable
from .wikidata_search import search as wikidata_search


def _snapshot_prefixes(snapshot) -> set[str]:
    if snapshot is None:
        return set()
    prefixes = set((snapshot.source_versions or {}).keys())
    prefixes.update(snapshot.releases.values_list("prefix", flat=True))
    if not prefixes:
        prefixes.update(snapshot.terms.values_list("prefix", flat=True).distinct())
    return prefixes


def _term_json(term) -> dict:
    return {
        "curie": term.curie,
        "prefix": term.prefix,
        "label": term.label,
        "definition": (term.definition or "")[:200],
        "synonyms": (term.synonyms or [])[:4],
    }


def _merge_wikidata(
    request, results: list[dict], q: str, limit: int
) -> tuple[list[dict], bool]:
    """Append Wikidata live results when the caller requests it.

    Triggered by ``?wikidata_live=1``; ``?root_qid=`` is optional.  Results
    whose CURIE already appears in *results* are silently dropped so local
    terms take precedence.

    Wikidata results carry ``"source": "wikidata"`` so the frontend can label
    them distinctly.  Annotation work must never block on Wikidata being
    reachable, so *results* is always returned; the second return value flags
    whether the live lookup itself was unreachable (as opposed to reachable
    but empty), so the caller can surface that distinctly instead of letting
    it look like "this term doesn't exist".
    """
    if request.GET.get("wikidata_live") != "1":
        return results, False
    root_qid = request.GET.get("root_qid") or None
    try:
        wd = wikidata_search(q, root_qid=root_qid, limit=limit)
    except WikidataUnavailable:
        return results, True
    except Exception:
        # Last-resort safety net for anything unanticipated — annotation
        # must never block on Wikidata, even if we can't say why it failed.
        return results, True
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
    return results, False


class OntologySearchView(LoginRequiredMixin, View):
    """GET /ontology/search/?q=<term>&prefixes=ELMO,ENVO&limit=20"""

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
        results = [_term_json(term) for term in terms]
        results, _wikidata_unavailable = _merge_wikidata(request, results, q, limit)
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
            # A populated graph must remain reproducible against its pinned
            # snapshot. A graph created before its project finished loading may
            # use the project snapshot until its first write pins that snapshot.
            snapshot = graph_snapshot or project_snapshot

        q = request.GET.get("q", "").strip()
        try:
            limit = min(max(int(request.GET.get("limit", 20)), 1), 50)
        except ValueError:
            limit = 20
        requested = {
            prefix.strip()
            for prefix in request.GET.get("prefixes", "").split(",")
            if prefix.strip()
        }

        available_prefixes = _snapshot_prefixes(snapshot)
        unavailable_prefixes = sorted(requested - available_prefixes)
        meta = {
            "snapshot_id": snapshot.pk if snapshot else None,
            "available_prefixes": sorted(available_prefixes),
            "unavailable_prefixes": unavailable_prefixes,
            "status": (
                "unavailable"
                if snapshot is None
                else "partial" if unavailable_prefixes else "ready"
            ),
        }

        raw_curies = request.GET.get("curies", "")
        if raw_curies:
            curies = [value.strip() for value in raw_curies.split(",") if value.strip()]
            terms = terms_by_curies(curies[:50], snapshot=snapshot)
            return JsonResponse(
                {"results": [_term_json(term) for term in terms], "meta": meta}
            )

        if len(q) < 2:
            return JsonResponse({"results": [], "meta": meta})

        # Local DB search — only possible when a snapshot exists.
        results: list[dict] = []
        if snapshot is not None:
            if graph and snapshot:
                allowed_prefixes = available_prefixes
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
                results = [_term_json(term) for term in terms]

        # Live lookup (Wikidata etc.) — always attempted when caller requests it,
        # even when the local snapshot is absent or yields nothing.
        results, wikidata_unavailable = _merge_wikidata(request, results, q, limit)
        if wikidata_unavailable:
            meta["wikidata_status"] = "unavailable"
        return JsonResponse({"results": results, "meta": meta})


class ProjectOntologyTermSuggestionView(LoginRequiredMixin, View):
    """POST /projects/<pk>/ontology/suggest/

    Logs a free-text term an annotator typed because nothing cached matched,
    for a curator to later batch and file upstream. Never blocks or mutates
    the annotation itself — the free-text value the annotator picked is
    already stored in the node/edge JSONB independently of this endpoint.
    """

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        if (
            not request.user.is_superuser
            and not ProjectMembership.objects.filter(
                project=project, user=request.user
            ).exists()
        ):
            raise PermissionDenied

        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        label = str(payload.get("label", "")).strip()
        target_ontology = str(payload.get("target_ontology", "")).strip()
        if not label or not target_ontology:
            return JsonResponse(
                {"error": "label and target_ontology are required."}, status=400
            )

        graph = None
        graph_pk = payload.get("graph") or request.GET.get("graph")
        if graph_pk:
            graph = CausalGraph.objects.filter(
                pk=graph_pk, document__project=project
            ).first()

        suggestion = OntologyTermSuggestion.objects.create(
            project=project,
            graph=graph,
            created_by=request.user,
            slot_name=str(payload.get("slot", ""))[:200],
            label=label[:1000],
            suggested_parent=str(payload.get("suggested_parent", ""))[:500],
            definition=str(payload.get("definition", "")),
            target_ontology=target_ontology[:100],
        )
        return JsonResponse({"ok": True, "id": suggestion.pk})
