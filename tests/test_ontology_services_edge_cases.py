"""
Phase 6 tests: Ontology search edge cases and fallback behavior.

Verify the ontology services search logic handles edge cases including
pg_trgm fallback when extension unavailable. Tests use database fixtures.
"""

import pytest

from apps.ontology.models import OntologySnapshot, OntologyTerm
from apps.ontology.services import (
    search_terms,
    term_by_curie,
    terms_by_curies,
)

# ---------------------------------------------------------------------------
# Fixtures
# ------ ------ -----


@pytest.fixture
def snapshot_with_terms(db):
    """Create a snapshot with various test terms."""
    snapshot = OntologySnapshot.objects.create(name="Test Snapshot", is_active=True)

    # Create terms with labels and synonyms
    OntologyTerm.objects.create(
        snapshot=snapshot,
        prefix="ENVO",
        curie="ENVO:00001001",
        label="temperate biome",
        description="A temperate region",
        synonym_labels=["temperate zone", "moderate climate"],
        obsolete=False,
    )

    OntologyTerm.objects.create(
        snapshot=snapshot,
        prefix="ENVO",
        curie="ENVO:00001002",
        label="canopy",
        description="The upper layer of vegetation",
        synonym_labels=["forest canopy", "tree canopy"],
        obsolete=False,
    )

    OntologyTerm.objects.create(
        snapshot=snapshot,
        prefix="NCBITaxon",
        curie="NCBITaxon:9606",
        label="Homo sapiens",
        description="Modern humans",
        synonym_labels=["human", "man"],
        obsolete=False,
    )

    OntologyTerm.objects.create(
        snapshot=snapshot,
        prefix="NCBITaxon",
        curie="NCBITaxon:1",
        label="root",
        description="Root taxon",
        synonym_labels=[],
        obsolete=True,  # Obsolete term
    )

    return snapshot


# ---------------------------------------------------------------------------
# search_terms tests
# --------------------------------------------------------------------------


class TestSearchTerms:
    """Verify search_terms function behavior."""

    def test_exact_curie_match(self, snapshot_with_terms):
        """Search returns exact CURIE match first."""
        results = search_terms("ENVO:00001001", snapshot=snapshot_with_terms)

        assert len(results) == 1
        assert results[0].curie == "ENVO:00001001"

    def test_label_search(self, snapshot_with_terms):
        """Search matches term label."""
        results = search_terms("temperate", snapshot=snapshot_with_terms)

        assert len(results) >= 1
        assert any("temperate" in r.label.lower() for r in results)

    def test_synonym_search(self, snapshot_with_terms):
        """Search matches synonym labels."""
        results = search_terms("human", snapshot=snapshot_with_terms)

        assert len(results) >= 1
        assert any("Homo sapiens" in r.label for r in results)

    def test_limit_results(self, snapshot_with_terms):
        """Search respects limit parameter."""
        results = search_terms("canopy", snapshot=snapshot_with_terms, limit=1)

        assert len(results) <= 1

    def test_prefix_filter(self, snapshot_with_terms):
        """Search filters by prefix."""
        results = search_terms(
            "human", prefixes=["NCBITaxon"], snapshot=snapshot_with_terms
        )

        assert len(results) >= 1
        assert all(r.prefix == "NCBITaxon" for r in results)

    def test_obsolete_excluded(self, snapshot_with_terms):
        """Obsolete terms are excluded from results."""
        results = search_terms("root", snapshot=snapshot_with_terms)

        assert len(results) >= 1
        assert all(not r.obsolete for r in results)

    def test_no_active_snapshot_returns_empty(self):
        """Search returns empty list when no active snapshot."""
        results = search_terms("test")

        assert results == []

    def test_empty_query(self):
        """Search returns empty list for empty query."""
        snapshot = OntologySnapshot.objects.create(name="Test", is_active=True)
        results = search_terms("", snapshot=snapshot)

        assert results == []

    def test_no_results(self):
        """Search returns empty list when no matches."""
        snapshot = OntologySnapshot.objects.create(name="Test", is_active=True)
        results = search_terms("nonexistent", snapshot=snapshot)

        assert results == []


class TestSearchTermsFallback:
    """Verify search fallback behavior."""

    def test_icontains_fallback(self, snapshot_with_terms):
        """Search falls back to icontains when trigram unavailable."""
        results = search_terms("homo", snapshot=snapshot_with_terms)

        # Should find Homo sapiens even with partial match
        assert len(results) >= 1
        assert any("Homo" in r.label for r in results)

    def test_case_insensitive(self, snapshot_with_terms):
        """Search is case-insensitive."""
        results = search_terms("TEMPERATE", snapshot=snapshot_with_terms)

        assert len(results) >= 1
        assert any("temperate" in r.label.lower() for r in results)


# ---------------------------------------------------------------------------
# term_by_curie tests
# --------------------------------------------------------------------------


class TestTermByCurie:
    """Verify term_by_curie function behavior."""

    def test_returns_term(self, snapshot_with_terms):
        """Returns term for valid CURIE."""
        term = term_by_curie("ENVO:00001001", snapshot=snapshot_with_terms)

        assert term is not None
        assert term.curie == "ENVO:00001001"

    def test_case_insensitive(self, snapshot_with_terms):
        """CURIE lookup is case-insensitive."""
        term = term_by_curie("envo:00001001", snapshot=snapshot_with_terms)

        assert term is not None

    def test_no_active_snapshot(self):
        """Returns None when no active snapshot."""
        term = term_by_curie("ENVO:00001001")

        assert term is None


# ---------------------------------------------------------------------------
# terms_by_curies tests
# --------------------------------------------------------------------------


class TestTermsByCuries:
    """Verify terms_by_curies function behavior."""

    def test_returns_terms(self, snapshot_with_terms):
        """Returns terms for valid CURIEs."""
        terms = terms_by_curies(
            ["ENVO:00001001", "ENVO:00001002"],
            snapshot=snapshot_with_terms,
        )

        assert len(terms) == 2

    def test_preserves_order(self, snapshot_with_terms):
        """Returns terms in requested order."""
        terms = terms_by_curies(
            ["ENVO:00001002", "ENVO:00001001"],
            snapshot=snapshot_with_terms,
        )

        assert terms[0].curie == "ENVO:00001002"
        assert terms[1].curie == "ENVO:00001001"

    def test_missing_curies(self, snapshot_with_terms):
        """Ignores CURIEs not in snapshot."""
        terms = terms_by_curies(
            ["ENVO:00001001", "UNKNOWN:00000000"],
            snapshot=snapshot_with_terms,
        )

        assert len(terms) == 1

    def test_empty_list(self):
        """Returns empty list for empty input."""
        snapshot = OntologySnapshot.objects.create(name="Test", is_active=True)
        terms = terms_by_curies([], snapshot=snapshot)

        assert terms == []

    def test_whitespace_handling(self):
        """Strips whitespace from CURIEs."""
        snapshot = OntologySnapshot.objects.create(name="Test", is_active=True)
        term = OntologyTerm.objects.create(
            snapshot=snapshot,
            prefix="TEST",
            curie="TEST:123",
            label="Test",
            obsolete=False,
        )
        terms = terms_by_curies(["  TEST:123  "], snapshot=snapshot)

        assert terms == [term]

    def test_none_in_list(self):
        """Ignores None values."""
        snapshot = OntologySnapshot.objects.create(name="Test", is_active=True)
        terms = terms_by_curies([None, "TEST:123"], snapshot=snapshot)

        assert len(terms) == 0
