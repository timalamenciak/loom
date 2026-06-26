"""Ontology search API — JSON endpoint consumed by ontology-autocomplete.js."""

from django.http import JsonResponse
from django.views import View

from .services import search_terms


class OntologySearchView(View):
    """GET /ontology/search/?q=<term>&prefixes=NCBITaxon,ENVO&limit=20"""

    def get(self, request):
        q = request.GET.get("q", "").strip()
        raw_prefixes = request.GET.get("prefixes", "").strip()
        prefixes = [p.strip() for p in raw_prefixes.split(",") if p.strip()] or None
        limit = min(int(request.GET.get("limit", 20)), 50)

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
