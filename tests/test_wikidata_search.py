"""
Phase 6 tests: Wikidata search API mock tests.

Verify the wikidata_search module handles network failures, rate limiting,
and API responses correctly. Tests mock the network layer - no actual API calls.
"""

from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from apps.ontology import wikidata_search

# ---------------------------------------------------------------------------
# Test fixtures
# ------ -----------


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before each test."""
    wikidata_search._cache.clear()
    yield
    wikidata_search._cache.clear()


# ---------------------------------------------------------------------------
# wbsearch tests
# ------ ----------


class TestWBSearch:
    """Verify _wbsearch function behavior."""

    def test_success(self):
        """Parses successful API response."""
        mock_enter = MagicMock()
        mock_enter.read.return_value = (
            b'{"search":[{"id":"Q123","label":"Test","description":"Desc"}]}'
        )

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_enter

            results = wikidata_search._wbsearch("test", 10)

            assert len(results) == 1
            assert results[0]["qid"] == "Q123"
            assert results[0]["label"] == "Test"

    def test_empty_response(self):
        """Returns empty list for no results."""
        mock_enter = MagicMock()
        mock_enter.read.return_value = b'{"search":[]}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_enter

            results = wikidata_search._wbsearch("test", 10)

            assert results == []

    def test_network_failure(self):
        """Raises WikidataUnavailable on network error — distinct from a
        reachable-but-empty result, so callers can tell "unreachable" apart
        from "no matching term"."""
        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = URLError("Network error")

            with pytest.raises(wikidata_search.WikidataUnavailable):
                wikidata_search._wbsearch("test", 10)

    def test_invalid_json(self):
        """Raises WikidataUnavailable for invalid JSON (malformed response,
        same as an unreachable service from the caller's perspective)."""
        mock_enter = MagicMock()
        mock_enter.read.return_value = b"not json"

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_enter

            with pytest.raises(wikidata_search.WikidataUnavailable):
                wikidata_search._wbsearch("test", 10)

    def test_filters_non_q_ids(self):
        """Filters out non-Q IDs."""
        mock_enter = MagicMock()
        mock_enter.read.return_value = b'{"search":[{"id":"P123","label":"Property"},{"id":"Q123","label":"Item"}]}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_enter

            results = wikidata_search._wbsearch("test", 10)

            assert len(results) == 1
            assert results[0]["qid"] == "Q123"


# ---------------------------------------------------------------------------
# sparql_filter tests
# ------ -----------


class TestSPARQLFilter:
    """Verify _sparql_filter function behavior."""

    def test_success(self):
        """Parses successful SPARQL response."""
        mock_enter = MagicMock()
        mock_enter.read.return_value = b'{"results":{"bindings":[{"item":{"value":"http://www.wikidata.org/entity/Q123"}}]}}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_enter

            results = wikidata_search._sparql_filter(["Q123"], None)

            assert results == {"Q123"}

    def test_empty_response(self):
        """Returns empty set for no results."""
        mock_enter = MagicMock()
        mock_enter.read.return_value = b'{"results":{"bindings":[]}}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_enter

            results = wikidata_search._sparql_filter(["Q123"], None)

            assert results == set()

    def test_network_failure(self):
        """Returns empty set on network error."""
        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = URLError("Network error")

            results = wikidata_search._sparql_filter(["Q123"], None)

            assert results == set()

    def test_empty_qids(self):
        """Returns empty set for empty input."""
        results = wikidata_search._sparql_filter([], None)

        assert results == set()


# ---------------------------------------------------------------------------
# claim_filter tests
# ------ -----------


class TestClaimFilter:
    """Verify _claim_filter function behavior."""

    def test_success_with_taxon_rank(self):
        """Returns QIDs with P105 (taxon rank)."""
        mock_enter = MagicMock()
        mock_enter.read.return_value = b'{"entities":{"Q123":{"claims":{"P105":[{"mainsnak":{"datavalue":{"value":{"id":"Q123"}}}}]}}}}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_enter

            results = wikidata_search._claim_filter(["Q123"], None)

            assert results == {"Q123"}

    def test_success_with_instance_of(self):
        """Returns QIDs with P31 (instance of) when root is Q16521."""
        mock_enter = MagicMock()
        mock_enter.read.return_value = b'{"entities":{"Q123":{"claims":{"P31":[{"mainsnak":{"datavalue":{"value":{"id":"Q16521"}}}}]}}}}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_enter

            results = wikidata_search._claim_filter(["Q123"], "Q16521")

            assert results == {"Q123"}

    def test_network_failure(self):
        """Returns empty set on network error."""
        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = URLError("Network error")

            results = wikidata_search._claim_filter(["Q123"], None)

            assert results == set()

    def test_empty_qids(self):
        """Returns empty set for empty input."""
        results = wikidata_search._claim_filter([], None)

        assert results == set()


# ---------------------------------------------------------------------------
# search function tests
# ------ ---------


class TestSearchFunction:
    """Verify search function behavior."""

    def test_success(self):
        """Returns properly formatted results."""
        mock_enter = MagicMock()
        mock_enter.read.return_value = (
            b'{"search":[{"id":"Q123","label":"Test","description":"Desc"}]}'
        )

        with (
            patch(
                "apps.ontology.wikidata_search.urllib.request.urlopen"
            ) as mock_urlopen,
            patch("apps.ontology.wikidata_search._claim_filter", return_value={"Q123"}),
        ):
            mock_urlopen.return_value.__enter__.return_value = mock_enter

            results = wikidata_search.search("test", root_qid="Q16521")

            assert len(results) == 1
            assert results[0]["curie"] == "WD:Q123"
            assert results[0]["label"] == "Test"

    def test_cache_hit(self):
        """Returns cached results for same query."""
        mock_enter = MagicMock()
        mock_enter.read.return_value = (
            b'{"search":[{"id":"Q123","label":"Test","description":"Desc"}]}'
        )

        with (
            patch(
                "apps.ontology.wikidata_search.urllib.request.urlopen"
            ) as mock_urlopen,
            patch("apps.ontology.wikidata_search._claim_filter", return_value={"Q123"}),
        ):
            mock_urlopen.return_value.__enter__.return_value = mock_enter

            # First call populates cache
            result1 = wikidata_search.search("test", root_qid="Q16521")
            # Second call should use cache (no network calls)
            result2 = wikidata_search.search("test", root_qid="Q16521")

            assert result1 == result2
            assert mock_urlopen.call_count == 1  # Only first call hit network

    def test_limits_results(self):
        """Respects limit parameter."""
        mock_enter = MagicMock()
        mock_enter.read.return_value = b'{"search":[{"id":"Q1","label":"A","description":""},{"id":"Q2","label":"B","description":""},{"id":"Q3","label":"C","description":""}]}'

        with (
            patch(
                "apps.ontology.wikidata_search.urllib.request.urlopen"
            ) as mock_urlopen,
            patch(
                "apps.ontology.wikidata_search._claim_filter",
                return_value={"Q1", "Q2", "Q3"},
            ),
        ):
            mock_urlopen.return_value.__enter__.return_value = mock_enter

            results = wikidata_search.search("test", root_qid="Q16521", limit=2)

            assert len(results) <= 2
