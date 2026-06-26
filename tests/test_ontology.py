"""
Phase 4 tests: ontology models, search service, search API endpoint.

Pure-Python loader tests use an in-memory OBO snippet without network access.
DB tests (TestSearchTerms, TestOntologySearchView) need Postgres.
"""

import io

import pytest


# ---------------------------------------------------------------------------
# Minimal OBO fixture used across tests
# ---------------------------------------------------------------------------

_MINI_OBO = """\
format-version: 1.2
ontology: test

[Term]
id: ENVO:00001001
name: temperate biome
def: "A biome characterized by temperate conditions." []
synonym: "temperate zone" EXACT []

[Term]
id: ENVO:00001002
name: canopy
def: "The uppermost layer of vegetation in a forest." []
synonym: "forest canopy" EXACT []

[Term]
id: PATO:0002019
name: abundance
def: "A quality of being plentiful or available in large quantities." []
synonym: "prevalence" EXACT []

[Term]
id: NCBITaxon:712036
name: Rhamnus cathartica
def: "European buckthorn. A shrub species in family Rhamnaceae." []
synonym: "buckthorn" EXACT []
synonym: "common buckthorn" EXACT []

[Term]
id: NCBITaxon:1
name: root
is_obsolete: true
"""


# ---------------------------------------------------------------------------
# Pure-Python loader tests (no network, no DB)
# ---------------------------------------------------------------------------


class TestOboParser:
    """Verify pronto can parse our mini OBO and extract the fields we need."""

    def test_parse_mini_obo(self):
        import pronto

        ont = pronto.Ontology(io.BytesIO(_MINI_OBO.encode()))
        ids = {str(t.id) for t in ont.terms()}
        assert "ENVO:00001001" in ids
        assert "NCBITaxon:712036" in ids

    def test_synonym_extraction(self):
        import pronto

        ont = pronto.Ontology(io.BytesIO(_MINI_OBO.encode()))
        term = ont["NCBITaxon:712036"]
        syns = [s.description for s in term.synonyms]
        assert "buckthorn" in syns

    def test_obsolete_flag(self):
        import pronto

        ont = pronto.Ontology(io.BytesIO(_MINI_OBO.encode()))
        term = ont["NCBITaxon:1"]
        assert term.obsolete

    def test_definition_text(self):
        import pronto

        ont = pronto.Ontology(io.BytesIO(_MINI_OBO.encode()))
        term = ont["ENVO:00001001"]
        assert "temperate" in (str(term.definition) if term.definition else "")


# ---------------------------------------------------------------------------
# DB-backed fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def snapshot(db):
    from apps.ontology.models import OntologySnapshot

    return OntologySnapshot.objects.create(name="test-snapshot", is_active=True)


@pytest.fixture
def terms(snapshot):
    """Load the mini OBO into the test snapshot via the loader."""
    import pronto

    from apps.ontology.models import OntologyTerm

    ont = pronto.Ontology(io.BytesIO(_MINI_OBO.encode()))

    batch = []
    for term in ont.terms():
        curie = str(term.id)
        prefix = curie.split(":")[0] if ":" in curie else "UNKNOWN"
        syns = [s.description for s in (term.synonyms or [])]
        batch.append(
            OntologyTerm(
                snapshot=snapshot,
                prefix=prefix,
                curie=curie,
                label=term.name or curie,
                synonyms=syns,
                synonym_labels=" ".join(syns),
                definition=str(term.definition) if term.definition else "",
                obsolete=bool(term.obsolete),
            )
        )

    OntologyTerm.objects.bulk_create(batch, ignore_conflicts=True)
    return OntologyTerm.objects.filter(snapshot=snapshot)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestOntologySnapshotModel:
    def test_only_one_active(self, db):
        from apps.ontology.models import OntologySnapshot

        s1 = OntologySnapshot.objects.create(name="s1", is_active=True)
        s2 = OntologySnapshot.objects.create(name="s2", is_active=True)
        s1.refresh_from_db()
        assert not s1.is_active
        assert s2.is_active

    def test_get_active(self, snapshot):
        from apps.ontology.models import OntologySnapshot

        assert OntologySnapshot.get_active() == snapshot


class TestOntologyTermModel:
    def test_terms_created(self, terms):
        assert terms.filter(obsolete=False).count() == 4  # excludes NCBITaxon:1

    def test_str(self, terms):
        t = terms.get(curie="ENVO:00001001")
        assert "temperate biome" in str(t)
        assert "ENVO:00001001" in str(t)

    def test_prefix_indexed(self, terms):
        envo = terms.filter(prefix="ENVO")
        assert envo.count() == 2

    def test_synonym_labels_populated(self, terms):
        t = terms.get(curie="NCBITaxon:712036")
        assert "buckthorn" in t.synonym_labels


# ---------------------------------------------------------------------------
# Search service tests (Phase 4 acceptance criterion)
# ---------------------------------------------------------------------------


class TestSearchTerms:
    def test_search_buckthorn(self, terms, snapshot):
        from apps.ontology.services import search_terms

        results = search_terms("buckthorn", snapshot=snapshot)
        curies = [r.curie for r in results]
        assert "NCBITaxon:712036" in curies

    def test_search_canopy(self, terms, snapshot):
        from apps.ontology.services import search_terms

        results = search_terms("canopy", snapshot=snapshot)
        curies = [r.curie for r in results]
        assert "ENVO:00001002" in curies

    def test_search_abundance(self, terms, snapshot):
        from apps.ontology.services import search_terms

        results = search_terms("abundance", snapshot=snapshot)
        curies = [r.curie for r in results]
        assert "PATO:0002019" in curies

    def test_exact_curie_lookup(self, terms, snapshot):
        from apps.ontology.services import search_terms

        results = search_terms("ENVO:00001001", snapshot=snapshot)
        assert len(results) == 1
        assert results[0].label == "temperate biome"

    def test_prefix_filter(self, terms, snapshot):
        from apps.ontology.services import search_terms

        results = search_terms("a", prefixes=["PATO"], snapshot=snapshot)
        assert all(r.prefix == "PATO" for r in results)

    def test_obsolete_excluded(self, terms, snapshot):
        from apps.ontology.services import search_terms

        results = search_terms("root", snapshot=snapshot)
        curies = [r.curie for r in results]
        assert "NCBITaxon:1" not in curies

    def test_no_active_snapshot_returns_empty(self, db):
        from apps.ontology.services import search_terms

        # No snapshot created → returns []
        results = search_terms("buckthorn")
        assert results == []

    def test_short_query_returns_empty(self, snapshot):
        from apps.ontology.services import search_terms

        assert search_terms("") == []
        assert search_terms("a", snapshot=snapshot) != []  # single char still searched (icontains)

    def test_term_by_curie(self, terms, snapshot):
        from apps.ontology.services import term_by_curie

        t = term_by_curie("ENVO:00001001", snapshot=snapshot)
        assert t is not None
        assert t.label == "temperate biome"


# ---------------------------------------------------------------------------
# API view tests
# ---------------------------------------------------------------------------


class TestOntologySearchView:
    def test_json_response(self, terms, snapshot):
        from django.test import Client

        client = Client()
        resp = client.get("/ontology/search/?q=buckthorn&prefixes=NCBITaxon")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        curies = [r["curie"] for r in data["results"]]
        assert "NCBITaxon:712036" in curies

    def test_short_query_empty(self, snapshot):
        from django.test import Client

        client = Client()
        resp = client.get("/ontology/search/?q=b")
        assert resp.status_code == 200
        assert resp.json() == {"results": []}

    def test_result_shape(self, terms, snapshot):
        from django.test import Client

        client = Client()
        resp = client.get("/ontology/search/?q=temperate")
        data = resp.json()
        assert len(data["results"]) >= 1
        first = data["results"][0]
        assert "curie" in first
        assert "label" in first
        assert "definition" in first
        assert "synonyms" in first
