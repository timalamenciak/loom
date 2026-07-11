"""Ontology search API — JSON endpoint consumed by ontology-autocomplete.js."""

import json
import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.annotation.models import CausalGraph
from apps.projects.models import Project, ProjectMembership

from .loaders import load_ontology, ontology_entries
from .models import AdHocOntologySource, OntologyRelease, OntologyTermSuggestion
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
        project_available_prefixes = _snapshot_prefixes(project_snapshot)
        outdated_prefixes = []
        if (
            graph_snapshot is not None
            and project_snapshot is not None
            and graph_snapshot.pk != project_snapshot.pk
        ):
            outdated_prefixes = sorted(
                (requested & project_available_prefixes) - available_prefixes
            )
        unavailable_prefixes = sorted(requested - available_prefixes)
        meta = {
            "snapshot_id": snapshot.pk if snapshot else None,
            "available_prefixes": sorted(available_prefixes),
            "project_available_prefixes": sorted(project_available_prefixes),
            "unavailable_prefixes": unavailable_prefixes,
            "outdated_prefixes": outdated_prefixes,
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


_UPLOAD_EXTENSIONS = {".obo", ".owl", ".yaml", ".yml"}


class OntologyManageListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """Staff-only: GET /ontology/manage/ — every loaded OntologyRelease."""

    raise_exception = True
    model = OntologyRelease
    queryset = OntologyRelease.objects.all().order_by("name")
    template_name = "ontology/ontology_list.html"
    context_object_name = "releases"

    def test_func(self):
        return self.request.user.is_staff


class OntologyReloadView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Staff-only: POST /ontology/manage/<pk>/reload/ — re-fetch a release's source."""

    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff

    def post(self, request, pk):
        release = get_object_or_404(OntologyRelease, pk=pk)
        try:
            _snapshot, count = load_ontology(release.name, source=release.source_url)
            messages.success(request, f"Reloaded {release.name}: {count:,} terms.")
        except Exception as exc:
            OntologyRelease.objects.filter(pk=pk).update(
                status=OntologyRelease.STATUS_FAILED, error=str(exc)
            )
            messages.error(request, f"Reload of {release.name} failed: {exc}")
        return redirect("ontology-manage-list")


class OntologyDeleteView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Staff-only: POST /ontology/manage/<pk>/delete/ — drop a release and its terms."""

    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff

    def post(self, request, pk):
        release = get_object_or_404(OntologyRelease, pk=pk)
        name = release.name
        release.terms.all().delete()
        release.delete()
        messages.success(request, f"Deleted {name} and its terms.")
        return redirect("ontology-manage-list")


class OntologyUploadView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Staff-only: GET/POST /ontology/manage/upload/ — register + load an ad hoc source.

    Accepts an OBO/OWL or LinkML YAML file directly (rather than a name already
    present in config/ontologies.yaml), so it registers an ``AdHocOntologySource``
    row first — ``load_ontology`` resolves *name* through that config lookup same
    as any YAML-configured ontology, it just doesn't know the difference.
    """

    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff

    def get(self, request):
        return render(request, "ontology/ontology_upload.html", {})

    def post(self, request):
        name = request.POST.get("name", "").strip()
        prefix = request.POST.get("prefix", "").strip()[:10]
        upload = request.FILES.get("source_file")
        ctx = {"name": name, "prefix": prefix}

        if not name or not prefix:
            ctx["error"] = "Name and prefix are required."
            return render(request, "ontology/ontology_upload.html", ctx)
        if not upload:
            ctx["error"] = "Choose a source file to upload."
            return render(request, "ontology/ontology_upload.html", ctx)

        ext = Path(upload.name).suffix.lower()
        if ext not in _UPLOAD_EXTENSIONS:
            ctx["error"] = (
                f"Unsupported file type '{ext or upload.name}'. "
                f"Allowed: {', '.join(sorted(_UPLOAD_EXTENSIONS))}."
            )
            return render(request, "ontology/ontology_upload.html", ctx)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                for chunk in upload.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            AdHocOntologySource.objects.update_or_create(
                name=name,
                defaults={
                    "prefix": prefix,
                    "url": f"file://{tmp_path}",
                    "created_by": request.user,
                },
            )
            _snapshot, count = load_ontology(name=name, source=tmp_path)
            ctx["success"] = True
            ctx["term_count"] = count
        except Exception as exc:
            ctx["error"] = f"Could not load ontology: {exc}"
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

        return render(request, "ontology/ontology_upload.html", ctx)


class OntologyBrowseView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Staff-only: GET /ontology/manage/<pk>/browse/ — search box for one release.

    Read-only diagnostic page: confirms a load succeeded and lets a curator
    look up a specific term. The search box itself hits OntologyTermSearchView
    over HTMX rather than submitting a form.
    """

    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff

    def get(self, request, pk):
        release = get_object_or_404(OntologyRelease, pk=pk)
        return render(request, "ontology/ontology_browse.html", {"release": release})


class OntologyTermSearchView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Staff-only: GET /ontology/manage/<pk>/search/?q=... — HTMX partial of matching terms.

    Scoped by the release's prefix within the active snapshot via the
    existing ``search_terms()`` — there's no ``release_id`` filter on that
    function, and a release is only searchable once it is linked into a
    snapshot, which every ``load_ontology()`` call already does. Good enough
    for "did my load work / what did it produce", which is this view's job.
    """

    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff

    def get(self, request, pk):
        release = get_object_or_404(OntologyRelease, pk=pk)
        q = request.GET.get("q", "").strip()
        terms = search_terms(q, prefixes=[release.prefix], limit=20) if q else []
        return render(
            request,
            "ontology/partials/term_results.html",
            {"release": release, "terms": terms, "q": q},
        )
