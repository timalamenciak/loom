"""
Phase 6 tests: Project deletion with transactional file cleanup.

Verify the delete_project function cleans up files and generates audit
events transactionally. Tests use database fixtures.
"""

from unittest.mock import Mock

import pytest
from django.core.files.base import ContentFile

from apps.annotation.models import CausalGraph, Edge, Node
from apps.audit.models import AuditEvent
from apps.projects.models import Assignment, Document, Project, ProjectMembership
from apps.projects.services import delete_project

# ---------------------------------------------------------------------------
# Fixtures
# ------ ------ -----


@pytest.fixture
def project_with_file(db, tmp_path, settings):
    """Create a project with an attached PDF file."""
    # Override MEDIA_ROOT for test isolation
    settings.MEDIA_ROOT = str(tmp_path / "media")

    project = Project.objects.create(name="Test Project")

    # Create a document with a PDF
    doc = Document.objects.create(
        project=project,
        title="Test Document",
        source=Document.SOURCE_RIS_IMPORT,
        canonical_text="Test abstract",
    )

    # Create a fake PDF file
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_text("%PDF-1.4 fake PDF content for testing")

    # Manually set the file to avoid storage complexity
    doc.pdf_file.save("test.pdf", ContentFile(b"%PDF-1.4 fake content"), save=True)

    return project


@pytest.fixture
def project_with_graph(db):
    """Create a project with a graph containing nodes and edges."""
    project = Project.objects.create(name="Test Project")

    # Create a simple schema version
    from apps.schemas.models import SchemaVersion

    schema = SchemaVersion.objects.create(
        name="Test Schema",
        version="0.4.0",
        linkml_yaml="""
id: https://example.org/test
name: test
imports: [linkml:types]
classes:
  CausalNode:
    attributes:
      name:
        range: string
  CausalEdge:
    attributes:
      predicate:
        range: string
""",
        sha256="a" * 64,
    )

    # Create graph with node and edge
    graph = CausalGraph.objects.create(
        document=Document.objects.create(
            project=project,
            title="Doc",
            source=Document.SOURCE_RIS_IMPORT,
            canonical_text="Abstract",
        ),
        schema_version=schema,
        source_document={},
    )

    node = Node.objects.create(
        graph=graph,
        name="Test Node",
        category="entity",
        data={"name": "Test Node"},
        schema_version=schema,
    )

    Edge.objects.create(
        graph=graph,
        subject=node,
        object=node,
        predicate="causal",
        data={"predicate": "causal"},
        schema_version=schema,
    )

    return project


# ---------------------------------------------------------------------------
# delete_project tests
# --------------------------------------------------------------------------


class TestDeleteProject:
    """Verify delete_project function behavior."""

    def test_deletes_project(self, db):
        """Project is deleted from database."""
        project = Project.objects.create(name="Test Project")

        delete_project(project, Mock(username="admin"))

        assert not Project.objects.filter(pk=project.pk).exists()

    def test_generates_audit_event(self, db):
        """Audit event is created for deletion."""
        project = Project.objects.create(name="Test Project")
        actor = Mock(username="admin")

        delete_project(project, actor)

        audit = AuditEvent.objects.get(
            action="project.delete",
            target_type="Project",
            target_id=str(project.pk),
        )
        assert audit.actor == actor
        assert "documents" in audit.diff
        assert "schema_sha256" in audit.diff

    def test_cascades_to_graphs(self, db):
        """Graphs are deleted with project."""
        project = Project.objects.create(name="Test Project")
        from apps.schemas.models import SchemaVersion

        schema = SchemaVersion.objects.create(
            name="Schema",
            version="0.4.0",
            linkml_yaml="id: test\nimports: [linkml:types]",
            sha256="a" * 64,
        )
        graph = CausalGraph.objects.create(
            document=Document.objects.create(
                project=project,
                title="Doc",
                source=Document.SOURCE_RIS_IMPORT,
                canonical_text="Abstract",
            ),
            schema_version=schema,
            source_document={},
        )

        delete_project(project, Mock(username="admin"))

        assert not CausalGraph.objects.filter(pk=graph.pk).exists()

    def test_cascades_to_nodes(self, db):
        """Nodes are deleted with project."""
        project = Project.objects.create(name="Test Project")
        from apps.schemas.models import SchemaVersion

        schema = SchemaVersion.objects.create(
            name="Schema",
            version="0.4.0",
            linkml_yaml="id: test\nimports: [linkml:types]",
            sha256="a" * 64,
        )
        graph = CausalGraph.objects.create(
            document=Document.objects.create(
                project=project,
                title="Doc",
                source=Document.SOURCE_RIS_IMPORT,
                canonical_text="Abstract",
            ),
            schema_version=schema,
            source_document={},
        )
        node = Node.objects.create(
            graph=graph,
            name="Node",
            category="entity",
            data={"name": "Node"},
            schema_version=schema,
        )

        delete_project(project, Mock(username="admin"))

        assert not Node.objects.filter(pk=node.pk).exists()

    def test_cascades_to_edges(self, db):
        """Edges are deleted with project."""
        project = Project.objects.create(name="Test Project")
        from apps.schemas.models import SchemaVersion

        schema = SchemaVersion.objects.create(
            name="Schema",
            version="0.4.0",
            linkml_yaml="id: test\nimports: [linkml:types]",
            sha256="a" * 64,
        )
        graph = CausalGraph.objects.create(
            document=Document.objects.create(
                project=project,
                title="Doc",
                source=Document.SOURCE_RIS_IMPORT,
                canonical_text="Abstract",
            ),
            schema_version=schema,
            source_document={},
        )
        node1 = Node.objects.create(
            graph=graph,
            name="Node1",
            category="entity",
            data={"name": "Node1"},
            schema_version=schema,
        )
        node2 = Node.objects.create(
            graph=graph,
            name="Node2",
            category="entity",
            data={"name": "Node2"},
            schema_version=schema,
        )
        edge = Edge.objects.create(
            graph=graph,
            subject=node1,
            object=node2,
            predicate="causal",
            data={"predicate": "causal"},
            schema_version=schema,
        )

        delete_project(project, Mock(username="admin"))

        assert not Edge.objects.filter(pk=edge.pk).exists()

    def test_cascades_to_memberships(self, db):
        """Project memberships are deleted with project."""
        project = Project.objects.create(name="Test Project")
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create(username="member")

        ProjectMembership.objects.create(project=project, user=user)

        delete_project(project, Mock(username="admin"))

        assert not ProjectMembership.objects.filter(project=project).exists()

    def test_cascades_to_assignments(self, db):
        """Assignments are deleted with project."""
        project = Project.objects.create(name="Test Project")
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create(username="annotator")

        doc = Document.objects.create(
            project=project,
            title="Doc",
            source=Document.SOURCE_RIS_IMPORT,
            canonical_text="Abstract",
        )
        Assignment.objects.create(
            document=doc,
            project=project,
            annotator=user,
            status=Assignment.STATUS_ASSIGNED,
        )

        delete_project(project, Mock(username="admin"))

        assert not Assignment.objects.filter(project=project).exists()

    def test_eda_graphs_before_nodes(self, db):
        """Edges are deleted before nodes (foreign key order)."""
        project = Project.objects.create(name="Test Project")
        from apps.schemas.models import SchemaVersion

        schema = SchemaVersion.objects.create(
            name="Schema",
            version="0.4.0",
            linkml_yaml="id: test\nimports: [linkml:types]",
            sha256="a" * 64,
        )
        graph = CausalGraph.objects.create(
            document=Document.objects.create(
                project=project,
                title="Doc",
                source=Document.SOURCE_RIS_IMPORT,
                canonical_text="Abstract",
            ),
            schema_version=schema,
            source_document={},
        )
        node1 = Node.objects.create(
            graph=graph,
            name="Node1",
            category="entity",
            data={"name": "Node1"},
            schema_version=schema,
        )
        node2 = Node.objects.create(
            graph=graph,
            name="Node2",
            category="entity",
            data={"name": "Node2"},
            schema_version=schema,
        )
        edge = Edge.objects.create(
            graph=graph,
            subject=node1,
            object=node2,
            predicate="causal",
            data={"predicate": "causal"},
            schema_version=schema,
        )

        # Delete should not raise foreign key error
        delete_project(project, Mock(username="admin"))

        assert not Edge.objects.filter(pk=edge.pk).exists()
        assert not Node.objects.filter(pk__in=[node1.pk, node2.pk]).exists()

    def test_summary_returned(self, db):
        """Delete returns summary dict."""
        project = Project.objects.create(name="Test Project")
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create(username="member")

        ProjectMembership.objects.create(project=project, user=user)

        result = delete_project(project, Mock(username="admin"))

        assert "name" in result
        assert "documents" in result
        assert "members" in result
        assert "assignments" in result


class TestDeleteProjectTransactional:
    """Verify delete_project is truly transactional."""

    def test_rollback_on_error(self, db, monkeypatch):
        """Project not deleted if audit event fails."""
        project = Project.objects.create(name="Test Project")

        # Mock audit to fail
        def mock_create(*args, **kwargs):
            raise Exception("Simulated failure")

        monkeypatch.setattr(AuditEvent, "objects", Mock(create=mock_create))

        with pytest.raises(Exception):
            delete_project(project, Mock(username="admin"))

        # Project should still exist (transaction rolled back)
        assert Project.objects.filter(pk=project.pk).exists()

    def test_files_deleted_after_commit(self, db, tmp_path, settings):
        """PDF files are deleted after database commit."""
        settings.MEDIA_ROOT = str(tmp_path / "media")

        project = Project.objects.create(name="Test Project")

        doc = Document.objects.create(
            project=project,
            title="Doc",
            source=Document.SOURCE_RIS_IMPORT,
            canonical_text="Abstract",
        )

        pdf_path = tmp_path / "media" / "test.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_text("fake pdf")

        doc.pdf_file.save("test.pdf", ContentFile(b"fake"), save=True)

        delete_project(project, Mock(username="admin"))

        # File should be deleted
        assert not pdf_path.exists()

    def test_files_not_deleted_before_commit(self, db, tmp_path, settings, monkeypatch):
        """Files not deleted if transaction rolls back."""
        settings.MEDIA_ROOT = str(tmp_path / "media")

        project = Project.objects.create(name="Test Project")

        doc = Document.objects.create(
            project=project,
            title="Doc",
            source=Document.SOURCE_RIS_IMPORT,
            canonical_text="Abstract",
        )

        pdf_path = tmp_path / "media" / "test.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_text("fake pdf")

        doc.pdf_file.save("test.pdf", ContentFile(b"fake"), save=True)

        def fail_on_delete(*args, **kwargs):
            raise Exception("Simulated failure on delete_project")

        def mock_create(*args, **kwargs):
            raise Exception("Simulated failure")

        monkeypatch.setattr(AuditEvent.objects, "create", mock_create)

        with pytest.raises(Exception):
            delete_project(project, Mock(username="admin"))

        # File should still exist
        assert pdf_path.exists()
