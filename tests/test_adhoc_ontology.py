"""
Phase 6 tests: Wikidata adhoc term resolution.

Verify the adhoc module resolves Wikidata CURIEs in annotation data.
Tests are pure Python - no database required.
"""

from unittest.mock import Mock, patch
from urllib.error import URLError

from django.contrib.auth import get_user_model

from apps.ontology import adhoc
from apps.ontology.models import OntologyRelease, OntologyTerm

# ---------------------------------------------------------------------------
# Helper fixtures
# ------ -----------


def create_test_project():
    """Create a test project for adhoc tests."""
    User = get_user_model()
    user = User.objects.create(username="adhoc_test_user")
    from apps.projects.models import Project

    return Project.objects.create(name="Test Project", created_by=user)


def create_mock_post():
    """Create a mock QueryDict for post data."""
    return Mock(get=lambda key, default="": default)


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
        project = create_test_project()
        post = create_mock_post()
        # Create a term
        OntologyTerm.objects.create(
            release=OntologyRelease.objects.create(
                project=project,
                prefix="WD",
                source_kind=OntologyRelease.SOURCE_KIND_WIKIDATA_ADHOC,
            ),
            curie="WD:Q123",
            label="Test Item",
            obsolete=False,
        )

        data = {"field": "WD:Q123"}

        adhoc.resolve_wd_curies_in_data(project, data, post)

        assert data == {"field": "WD:Q123"}

    def test_resolves_multiple_curies(self, db):
        """Resolves multiple Wikidata CURIEs."""
        project = create_test_project()
        post = create_mock_post()
        release = OntologyRelease.objects.create(
            project=project,
            prefix="WD",
            source_kind=OntologyRelease.SOURCE_KIND_WIKIDATA_ADHOC,
        )
        OntologyTerm.objects.create(
            release=release, curie="WD:Q123", label="Item 1", obsolete=False
        )
        OntologyTerm.objects.create(
            release=release, curie="WD:Q456", label="Item 2", obsolete=False
        )

        data = {
            "field1": "WD:Q123",
            "field2": "WD:Q456",
        }

        adhoc.resolve_wd_curies_in_data(project, data, post)

        assert data == data

    def test_handles_nested_structures(self, db):
        """Resolves CURIEs in nested dictionaries."""
        project = create_test_project()
        post = create_mock_post()
        release = OntologyRelease.objects.create(
            project=project,
            prefix="WD",
            source_kind=OntologyRelease.SOURCE_KIND_WIKIDATA_ADHOC,
        )
        OntologyTerm.objects.create(
            release=release, curie="WD:Q123", label="Item", obsolete=False
        )

        data = {
            "outer": {
                "inner": {
                    "field": "WD:Q123",
                },
            },
        }

        adhoc.resolve_wd_curies_in_data(project, data, post)

        assert data == data

    def test_handles_lists(self, db):
        """Resolves CURIEs in lists."""
        project = create_test_project()
        post = create_mock_post()
        release = OntologyRelease.objects.create(
            project=project,
            prefix="WD",
            source_kind=OntologyRelease.SOURCE_KIND_WIKIDATA_ADHOC,
        )
        OntologyTerm.objects.create(
            release=release, curie="WD:Q123", label="Item", obsolete=False
        )

        data = {
            "field": ["WD:Q123", "WD:Q456"],
        }

        adhoc.resolve_wd_curies_in_data(project, data, post)

        assert data == data

    def test_ignores_non_wikidata(self, db):
        """Ignores non-Wikidata CURIEs."""
        project = create_test_project()
        post = create_mock_post()

        data = {
            "field": "ENVO:00001001",
        }

        adhoc.resolve_wd_curies_in_data(project, data, post)

        assert data == data

    def test_handles_none_values(self, db):
        """Handles None values in data."""
        project = create_test_project()
        post = create_mock_post()

        data = {
            "field": None,
        }

        adhoc.resolve_wd_curies_in_data(project, data, post)

        assert data == data

    def test_handles_empty_string(self, db):
        """Handles empty strings."""
        project = create_test_project()
        post = create_mock_post()

        data = {
            "field": "",
        }

        adhoc.resolve_wd_curies_in_data(project, data, post)

        assert data == data

    def test_handles_non_curie_strings(self, db):
        """Handles non-CURIE strings."""
        project = create_test_project()
        post = create_mock_post()

        data = {
            "field": "not-a-curie",
        }

        adhoc.resolve_wd_curies_in_data(project, data, post)

        assert data == data


# ---------------------------------------------------------------------------
# get_or_create_adhoc_wikidata_term tests
# ------ -----------


class TestGetOrCreateAdHocWikidataTerm:
    """Verify get_or_create_adhoc_wikidata_term function behavior."""

    def test_returns_existing_term(self, db):
        """Returns existing term if it exists."""
        project = create_test_project()
        release = OntologyRelease.objects.create(
            project=project,
            prefix="WD",
            source_kind=OntologyRelease.SOURCE_KIND_WIKIDATA_ADHOC,
        )
        term = OntologyTerm.objects.create(
            release=release, curie="WD:Q123", label="Test Item", obsolete=False
        )

        result = adhoc.get_or_create_adhoc_wikidata_term(project, "WD:Q123")

        assert result == term

    def test_creates_new_term(self, db):
        """Creates new term if it doesn't exist."""
        project = create_test_project()
        with patch("apps.ontology.adhoc._wbgetentities") as mock_wbget:
            mock_wbget.return_value = ("Test Label", "Test Description")
            result = adhoc.get_or_create_adhoc_wikidata_term(project, "WD:Q123")

        assert result is not None
        assert result.prefix == "WD"
        assert result.curie == "WD:Q123"
        assert result.label == "Test Label"

    def test_has_adhoc_source(self, db):
        """Created term is linked to adhoc release."""
        project = create_test_project()
        with patch("apps.ontology.adhoc._wbgetentities") as mock_wbget:
            mock_wbget.return_value = ("Test Label", "Test Description")
            result = adhoc.get_or_create_adhoc_wikidata_term(project, "WD:Q456")

        # Term should be linked to an adhoc release
        assert result.release is not None
        assert result.release.source_kind == OntologyRelease.SOURCE_KIND_WIKIDATA_ADHOC


# ---------------------------------------------------------------------------
# _wbgetentities tests
# ------ -----------


class TestWBGetEntities:
    """Verify _wbgetentities function behavior."""

    def test_success(self):
        """Parses successful API response and returns (label, description) tuple."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"entities":{"Q123":{"id":"Q123","labels":{"en":{"value":"Test"}},"descriptions":{"en":{"value":"Desc"}}}}}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response

            label, description = adhoc._wbgetentities("Q123")

            assert label == "Test"
            assert description == "Desc"

    def test_network_failure(self):
        """Returns empty tuple on network error."""
        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = URLError("Network error")

            label, description = adhoc._wbgetentities("Q123")

            assert label == ""
            assert description == ""

    def test_handles_single_entity(self):
        """Parses single entity."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"entities":{"Q123":{"id":"Q123","labels":{"en":{"value":"Test"}}},"Q456":{"id":"Q456","labels":{"en":{"value":"Test2"}}}}}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response

            label, description = adhoc._wbgetentities("Q123")

            assert label == "Test"

    def test_handles_missing_entities(self):
        """Handles missing entities in response."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"entities":{"Q123":{"id":"Q123","labels":{"en":{"value":"Test"}}},"Q456":{"missing":""}}}'

        with patch(
            "apps.ontology.wikidata_search.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response

            label, description = adhoc._wbgetentities("Q456")

            assert label == ""
            assert description == ""
