"""Tests for the staff-only ontology management views (apps/ontology/views.py)."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.ontology.models import (
    AdHocOntologySource,
    OntologyRelease,
    OntologySnapshot,
    OntologyTerm,
)

User = get_user_model()

MINI_OBO = b"""\
format-version: 1.2
ontology: test

[Term]
id: TEST:1
name: first term
"""

MINI_LINKML = b"""\
id: https://example.org/test-schema
name: test-schema
prefixes:
  linkml: https://w3id.org/linkml/
default_range: string
imports:
  - linkml:types
enums:
  ClaimStrength:
    permissible_values:
      Weak:
        description: "A weak causal claim."
      Strong:
        description: "A strong causal claim."
"""


@pytest.fixture
def staff_user(db):
    return User.objects.create_user("ontology-manager", password="x", is_staff=True)


class TestOntologyReloadView:
    def test_reload_view_updates_term_count(self, db, staff_user):
        release = OntologyRelease.objects.create(
            name="test",
            prefix="TEST",
            source_url="https://example.org/test.obo",
            source_sha256="abc123",
            term_count=1,
            status=OntologyRelease.STATUS_READY,
        )
        client = Client()
        client.force_login(staff_user)

        with patch("apps.ontology.views.load_ontology") as mock_load:
            mock_load.return_value = (object(), 42)
            response = client.post(
                reverse("ontology-manage-reload", args=[release.pk]), follow=True
            )

        mock_load.assert_called_once_with(release.name, source=release.source_url)
        assert response.status_code == 200
        assert response.redirect_chain[-1][0] == reverse("ontology-manage-list")
        messages = list(response.context["messages"])
        assert any("42 terms" in str(m) for m in messages)


class TestOntologyUploadView:
    def test_upload_obo(self, db, staff_user):
        client = Client()
        client.force_login(staff_user)
        upload = SimpleUploadedFile("mini.obo", MINI_OBO, content_type="text/plain")

        response = client.post(
            reverse("ontology-manage-upload"),
            {"name": "mini-obo", "prefix": "TEST", "source_file": upload},
        )

        assert response.status_code == 200
        release = OntologyRelease.objects.get(name="mini-obo")
        assert release.term_count > 0
        assert release.status == OntologyRelease.STATUS_READY
        assert AdHocOntologySource.objects.filter(name="mini-obo").exists()

    def test_upload_linkml_yaml(self, db, staff_user):
        client = Client()
        client.force_login(staff_user)
        upload = SimpleUploadedFile(
            "mini.yaml", MINI_LINKML, content_type="application/x-yaml"
        )

        response = client.post(
            reverse("ontology-manage-upload"),
            {"name": "mini-linkml", "prefix": "CS", "source_file": upload},
        )

        assert response.status_code == 200
        release = OntologyRelease.objects.get(name="mini-linkml")
        terms = OntologyTerm.objects.filter(release=release)
        assert terms.count() == 2
        assert set(terms.values_list("curie", flat=True)) == {
            "ClaimStrength:Weak",
            "ClaimStrength:Strong",
        }

    def test_upload_wrong_extension(self, db, staff_user):
        client = Client()
        client.force_login(staff_user)
        upload = SimpleUploadedFile(
            "mini.txt", b"not an ontology", content_type="text/plain"
        )

        response = client.post(
            reverse("ontology-manage-upload"),
            {"name": "mini-txt", "prefix": "TXT", "source_file": upload},
        )

        assert response.status_code == 200
        assert "Unsupported file type" in response.content.decode()
        assert not OntologyRelease.objects.filter(name="mini-txt").exists()


@pytest.fixture
def loaded_release(db):
    """An active-snapshot-linked release with one searchable term."""
    release = OntologyRelease.objects.create(
        name="claim-strength",
        prefix="ClaimStrength",
        source_url="https://example.org/claim-strength.yaml",
        source_sha256="def456",
        term_count=1,
        status=OntologyRelease.STATUS_READY,
    )
    OntologyTerm.objects.create(
        release=release,
        prefix="ClaimStrength",
        curie="ClaimStrength:Strong",
        label="Strong",
        definition="A strong causal claim.",
    )
    snapshot = OntologySnapshot.objects.create(name="test-snapshot", is_active=True)
    snapshot.releases.add(release)
    return release


class TestOntologyBrowseView:
    def test_browse_view_renders_search_box(self, db, staff_user, loaded_release):
        client = Client()
        client.force_login(staff_user)

        response = client.get(
            reverse("ontology-manage-browse", args=[loaded_release.pk])
        )

        assert response.status_code == 200
        body = response.content.decode()
        assert '<input type="search"' in body
        assert reverse("ontology-manage-search", args=[loaded_release.pk]) in body


class TestOntologyTermSearchView:
    def test_search_returns_matching_terms(self, db, staff_user, loaded_release):
        client = Client()
        client.force_login(staff_user)

        response = client.get(
            reverse("ontology-manage-search", args=[loaded_release.pk]), {"q": "Strong"}
        )

        assert response.status_code == 200
        body = response.content.decode()
        assert "ClaimStrength:Strong" in body
        assert "A strong causal claim." in body

    def test_search_empty_query_returns_no_results(
        self, db, staff_user, loaded_release
    ):
        client = Client()
        client.force_login(staff_user)

        response = client.get(
            reverse("ontology-manage-search", args=[loaded_release.pk]), {"q": ""}
        )

        assert response.status_code == 200
        assert "ClaimStrength:Strong" not in response.content.decode()
