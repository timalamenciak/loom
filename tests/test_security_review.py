"""Regression tests for the v1.0.0 security review — see
docs/security-review-v1.0.md for the full audit record. Covers the concrete
fixes made during that review: upload validation (extension allowlist, size
limits, magic-byte checks) for schema and ontology uploads, and HTML
sanitization of markdown-rendered canonical text before it's marked safe.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.ontology.models import OntologyRelease
from apps.schemas.models import SchemaVersion
from tests.schema_fixtures import latest_schema_path

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        "security-review-staff", password="x", is_staff=True
    )


@pytest.fixture
def annotator(db):
    return User.objects.create_user("security-review-annotator", password="x")


class TestSchemaUploadValidation:
    def test_rejects_non_yaml_extension(self, db, staff_user):
        client = Client()
        client.force_login(staff_user)
        upload = SimpleUploadedFile(
            "schema.txt", b"id: x\nname: x\n", content_type="text/plain"
        )

        response = client.post(reverse("schema-upload"), {"schema_file": upload})

        assert response.status_code == 200
        assert "Unsupported file type" in response.content.decode()
        assert SchemaVersion.objects.count() == 0

    def test_rejects_oversized_file(self, db, staff_user, settings):
        settings.MAX_SCHEMA_UPLOAD_BYTES = 10
        client = Client()
        client.force_login(staff_user)
        content = latest_schema_path().read_text(encoding="utf-8")
        upload = SimpleUploadedFile(
            "schema.yaml", content.encode("utf-8"), content_type="application/x-yaml"
        )

        response = client.post(reverse("schema-upload"), {"schema_file": upload})

        assert response.status_code == 200
        assert "may not exceed" in response.content.decode()
        assert SchemaVersion.objects.count() == 0


class TestOntologyUploadValidation:
    def test_rejects_oversized_file(self, db, staff_user, settings):
        settings.MAX_ONTOLOGY_UPLOAD_BYTES = 10
        client = Client()
        client.force_login(staff_user)
        upload = SimpleUploadedFile(
            "toy.obo",
            b"format-version: 1.2\nontology: toy\n\n[Term]\nid: T:1\nname: x\n",
            content_type="text/plain",
        )

        response = client.post(
            reverse("ontology-manage-upload"),
            {"name": "oversized-test", "prefix": "OVR", "source_file": upload},
        )

        assert response.status_code == 200
        assert "may not exceed" in response.content.decode()
        assert not OntologyRelease.objects.filter(name="oversized-test").exists()

    def test_rejects_obo_missing_format_version_header(self, db, staff_user):
        client = Client()
        client.force_login(staff_user)
        upload = SimpleUploadedFile(
            "fake.obo", b"this is not an obo file at all", content_type="text/plain"
        )

        response = client.post(
            reverse("ontology-manage-upload"),
            {"name": "fake-obo-test", "prefix": "FAK", "source_file": upload},
        )

        assert response.status_code == 200
        assert "not a valid OBO file" in response.content.decode()
        assert not OntologyRelease.objects.filter(name="fake-obo-test").exists()


@pytest.fixture
def project_with_markdown_document(staff_user, annotator, latest_schema):
    from apps.projects.models import Assignment, Document, Project, ProjectMembership

    project = Project.objects.create(
        name="Security Review Project",
        created_by=staff_user,
        active_schema=latest_schema,
    )
    ProjectMembership.objects.create(
        project=project, user=annotator, role=ProjectMembership.ROLE_ANNOTATOR
    )
    document = Document.objects.create(
        project=project,
        source=Document.SOURCE_MANUAL,
        title="XSS Test Doc",
        canonical_text="placeholder",
        canonical_markdown=(
            "Normal text.\n\n"
            "<script>alert('xss')</script>\n\n"
            '<p onclick="alert(1)">click me</p>'
        ),
    )
    Assignment.objects.create(
        project=project,
        document=document,
        annotator=annotator,
        assigned_by=staff_user,
        status=Assignment.STATUS_ASSIGNED,
    )
    return project, document


class TestMarkdownXSSSanitization:
    def test_script_tag_in_canonical_markdown_is_stripped(
        self, client, project_with_markdown_document, annotator
    ):
        project, document = project_with_markdown_document
        client.force_login(annotator)

        response = client.get(
            reverse("annotate", kwargs={"pk": project.pk, "doc_pk": document.pk})
        )

        assert response.status_code == 200
        body = response.content.decode()
        # The page legitimately embeds its own <script> tags for app JS — the
        # injected payload is what must be gone, not every <script> on the page.
        assert "alert('xss')" not in body
        assert "<script>alert" not in body
        assert 'onclick="alert(1)"' not in body
        assert "Normal text." in body
