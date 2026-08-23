"""Project.active_schema override vs. the system-active SchemaVersion.

Covers apps/annotation/views.py:get_schema_version(project), the helper
that centralizes the "project override, else system-active" fallback used
when AnnotationView creates a new graph for an annotator.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.annotation.models import CausalGraph
from apps.projects.models import Assignment, Document, Project, ProjectMembership
from apps.schemas.models import SchemaVersion
from tests.schema_fixtures import frozen_schema_path

User = get_user_model()


@pytest.fixture
def annotator(db):
    return User.objects.create_user("schema-override-annotator", password="pw")


@pytest.fixture
def project(db, annotator):
    project = Project.objects.create(name="Schema Override Test", created_by=annotator)
    ProjectMembership.objects.create(
        project=project, user=annotator, role=ProjectMembership.ROLE_ANNOTATOR
    )
    return project


@pytest.fixture
def document(project):
    return Document.objects.create(
        project=project,
        source="manual",
        title="Test document",
        canonical_text="Rhamnus cathartica increases soil nitrogen availability.",
    )


@pytest.fixture
def assignment(project, document, annotator):
    return Assignment.objects.create(
        project=project,
        document=document,
        annotator=annotator,
        assigned_by=annotator,
        status=Assignment.STATUS_ASSIGNED,
    )


@pytest.fixture
def project_override_schema(db):
    """A second, non-active SchemaVersion a project can pin to instead of
    whatever happens to be system-active."""
    content = frozen_schema_path("0.4.1").read_text(encoding="utf-8")
    return SchemaVersion.objects.create(
        version="0.4.1-project-override", linkml_yaml=content, is_active=False
    )


def _open_workspace(annotator, project, document):
    client = Client()
    client.force_login(annotator)
    return client.get(f"/annotation/{project.pk}/documents/{document.pk}/annotate/")


class TestProjectSchemaOverride:
    def test_project_uses_own_schema(
        self,
        project,
        document,
        assignment,
        annotator,
        frozen_schema_040,
        project_override_schema,
    ):
        """A project with active_schema set pins new graphs to that
        version, not to whatever SchemaVersion is system-active."""
        project.active_schema = project_override_schema
        project.save(update_fields=["active_schema"])

        resp = _open_workspace(annotator, project, document)

        assert resp.status_code == 200
        graph = CausalGraph.objects.get(document=document, annotator=annotator)
        assert graph.schema_version_id == project_override_schema.pk
        assert graph.schema_version_id != frozen_schema_040.pk

    def test_project_falls_back_to_active(
        self, project, document, assignment, annotator, frozen_schema_040
    ):
        """A project with no active_schema set falls back to the
        system-active SchemaVersion."""
        assert project.active_schema is None

        resp = _open_workspace(annotator, project, document)

        assert resp.status_code == 200
        graph = CausalGraph.objects.get(document=document, annotator=annotator)
        assert graph.schema_version_id == frozen_schema_040.pk
