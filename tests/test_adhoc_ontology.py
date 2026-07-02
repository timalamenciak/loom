"""
Phase 6 tests: Wikidata adhoc term resolution.

Verify the adhoc module resolves Wikidata CURIEs in annotation data.
Tests are pure Python - no database required.
"""

from unittest.mock import Mock, patch
from urllib.error import URLError

from apps.ontology import adhoc
from apps.ontology.models import OntologyTerm

# ---------------------------------------------------------------------------
# Helper fixtures
# ------ -----------


class MockEntity:
    """Mock Wikidata entity."""

    def __init__(self, qid, label, description=None):
        self.id = qid
        self.label = label
        self.description = description or ""


# ---------------------------------------------------------------------------
# resolve_wd_curies_in_data tests
# ------ -----------


class TestResolveWDCuriesInData:
    """Verify resolve_wd_curies_in_data function behavior."""

    def test_resolves_single_curie(self, db):
        """Resolves single Wikidata CURIE to OntologyTerm."""
        # Create a term
        OntologyTerm.objects.create(
            prefix="WD",
            curie="WD:Q123",
            label="Test Item",
            obsolete=False,
        )

        data = {"field": "WD:Q123"}

        result = adhoc.resolve_wd_curies_in_data(data)

        assert result == {"field": "WD:Q123"}

    def test_resolves_multiple_curies(self, db):
        """Resolves multiple Wikidata CURIEs."""
        OntologyTerm.objects.create(
            prefix="WD",
            curie="WD:Q123",
            label="Item 1",
            obsolete=False,
        )
        OntologyTerm.objects.create(
            prefix="WD",
            curie="WD:Q456",
            label="Item 2",
            obsolete=False,
        )

        data = {
            "field1": "WD:Q123",
            "field2": "WD:Q456",
        }

        result = adhoc.resolve_wd_curies_in_data(data)

        assert result == data

    def test_handles_nested_structures(self, db):
        """Resolves CURIEs in nested dictionaries."""
        OntologyTerm.objects.create(
            prefix="WD",
            curie="WD:Q123",
            label="Item",
            obsolete=False,
        )

        data = {
            "outer": {
                "inner": {
                    "field": "WD:Q123",
                },
            },
        }

        result = adhoc.resolve_wd_curies_in_data(data)

        assert result == data

    def test_handles_lists(self, db):
        """Resolves CURIEs in lists."""
        OntologyTerm.objects.create(
            prefix="WD",
            curie="WD:Q123",
            label="Item",
            obsolete=False,
        )

        data = {
            "field": ["WD:Q123", "WD:Q456"],
        }

        result = adhoc.resolve_wd_curies_in_data(data)

        assert result == data

    def test_ignores_non_wikidata(self, db):
        """Ignores non-Wikidata CURIEs."""
        data = {
            "field": "ENVO:00001001",
        }

        result = adhoc.resolve_wd_curies_in_data(data)

        assert result == data

    def test_handles_none_values(self, db):
        """Handles None values in data."""
        data = {
            "field": None,
        }

        result = adhoc.resolve_wd_curies_in_data(data)

        assert result == data

    def test_handles_empty_string(self, db):
        """Handles empty strings."""
        data = {
            "field": "",
        }

        result = adhoc.resolve_wd_curies_in_data(data)

        assert result == data

    def test_handles_non_curie_strings(self, db):
        """Handles non-CURIE strings."""
        data = {
            "field": "not-a-curie",
        }

        result = adhoc.resolve_wd_curies_in_data(data)

        assert result == data


# ---------------------------------------------------------------------------
# get_or_create_adhoc_wikidata_term tests
# ------ -----------


class TestGetOrCreateAdHocWikidataTerm:
    """Verify get_or_create_adhoc_wikidata_term function behavior."""

    def test_returns_existing_term(self, db):
        """Returns existing term if it exists."""
        term = OntologyTerm.objects.create(
            prefix="WD",
            curie="WD:Q123",
            label="Test Item",
            obsolete=False,
        )

        result = adhoc.get_or_create_adhoc_wikidata_term("WD:Q123")

        assert result == term

    def test_creates_new_term(self, db):
        """Creates new term if it doesn't exist."""
        result = adhoc.get_or_create_adhoc_wikidata_term("WD:Q123")

        assert result is not None
        assert result.prefix == "WD"
        assert result.curie == "WD:Q123"
        assert result.label == "WD:Q123"  # Default label

    def test_has_adhoc_source(self, db):
        """Created term has adhoc source."""
        result = adhoc.get_or_create_adhoc_wikidata_term("WD:Q456")

        assert result.source == OntologyTerm.SOURCE_ADHOC


# ---------------------------------------------------------------------------
# _wbgetentities tests
# ------ -----------


class TestWBGetEntities:
    """Verify _wbgetentities function behavior."""

    def test_success(self):
        """Parses successful API response."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"entities":{"Q123":{"id":"Q123","labels":{"en":{"value":"Test"}},"descriptions":{"en":{"value":"Desc"}}}}}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response

            entities = adhoc._wbgetentities(["Q123"])

            assert "Q123" in entities
            assert entities["Q123"]["labels"]["en"]["value"] == "Test"

    def test_network_failure(self):
        """Returns empty dict on network error."""
        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = URLError("Network error")

            entities = adhoc._wbgetentities(["Q123"])

            assert entities == {}

    def test_handles_multiple_entities(self):
        """Parses multiple entities."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"entities":{"Q123":{"id":"Q123","labels":{"en":{"value":"Test"}}},"Q456":{"id":"Q456","labels":{"en":{"value":"Test2"}}}}}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response

            entities = adhoc._wbgetentities(["Q123", "Q456"])

            assert "Q123" in entities
            assert "Q456" in entities

    def test_handles_missing_entities(self):
        """Handles missing entities in response."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"entities":{"Q123":{"id":"Q123","labels":{"en":{"value":"Test"}}},"Q456":{"missing":""}}}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response

            entities = adhoc._wbgetentities(["Q123", "Q456"])

            assert "Q123" in entities
            assert "Q456" not in entities or entities["Q456"].get("missing") == ""
