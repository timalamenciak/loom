"""Ontology term search service.

Search strategy (in order):
1. Exact CURIE match (e.g. "ENVO:00001001").
2. Trigram similarity on label (if pg_trgm extension is available).
3. Case-insensitive substring match on label + synonym_labels.
"""

from __future__ import annotations

from django.db.models import Q

from .models import OntologySnapshot, OntologyTerm


def get_active_snapshot() -> OntologySnapshot | None:
    return OntologySnapshot.get_active()


def search_terms(
    query: str,
    prefixes: list[str] | None = None,
    snapshot: OntologySnapshot | None = None,
    limit: int = 20,
) -> list[OntologyTerm]:
    """Return up to *limit* OntologyTerm objects matching *query*.

    Args:
        query: Free text or CURIE string.
        prefixes: Optional list of ontology prefixes to restrict results
                  (e.g. ["NCBITaxon", "ENVO"]).
        snapshot: Which snapshot to search; defaults to the active one.
        limit: Maximum results.
    """
    if not query:
        return []

    if snapshot is None:
        snapshot = get_active_snapshot()
    if snapshot is None:
        return []

    qs = OntologyTerm.objects.filter(snapshot=snapshot, obsolete=False)
    if prefixes:
        qs = qs.filter(prefix__in=prefixes)

    # 1. Exact CURIE lookup
    if ":" in query:
        exact = qs.filter(curie__iexact=query).first()
        if exact:
            return [exact]

    # 2. Trigram similarity (optional; requires pg_trgm extension + GIN index)
    try:
        from django.contrib.postgres.search import TrigramSimilarity

        results = list(
            qs.annotate(sim=TrigramSimilarity("label", query))
            .filter(sim__gt=0.15)
            .order_by("-sim")[:limit]
        )
        if results:
            return results
    except Exception:
        pass

    # 3. icontains fallback (label + synonym_labels)
    return list(
        qs.filter(
            Q(label__icontains=query) | Q(synonym_labels__icontains=query)
        ).order_by("label")[:limit]
    )


def term_by_curie(curie: str, snapshot: OntologySnapshot | None = None) -> OntologyTerm | None:
    if snapshot is None:
        snapshot = get_active_snapshot()
    if snapshot is None:
        return None
    return OntologyTerm.objects.filter(snapshot=snapshot, curie__iexact=curie).first()
