"""View-level tests for the web bulk import/export flow (apps/export/views.py):
upload -> preview -> apply, permission gating via require_import_access, and
the Excel export/template endpoint.
"""

import io

import pytest
import yaml
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.annotation.models import Node
from apps.annotation.services import create_graph, create_node
from apps.projects.models import Assignment, Document, Project, ProjectMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user("import-admin", password="pw")


@pytest.fixture
def annotator_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user("import-annotator", password="pw")


@pytest.fixture
def project(admin_user, annotator_user, frozen_schema_040):
    project = Project.objects.create(
        name="Import View Test", created_by=admin_user, active_schema=frozen_schema_040
    )
    ProjectMembership.objects.create(project=project, user=admin_user, role="admin")
    ProjectMembership.objects.create(
        project=project, user=annotator_user, role="annotator"
    )
    return project


@pytest.fixture
def document(project):
    return Document.objects.create(
        project=project,
        source=Document.SOURCE_MANUAL,
        title="Import View Doc",
        canonical_text="Buckthorn increases soil nitrogen.",
    )


@pytest.fixture
def graph(document, admin_user, frozen_schema_040):
    return create_graph(document, admin_user, frozen_schema_040)


@pytest.fixture
def assignment(project, document, graph, annotator_user, admin_user):
    return Assignment.objects.create(
        project=project,
        document=document,
        graph=graph,
        annotator=annotator_user,
        assigned_by=admin_user,
        status=Assignment.STATUS_ASSIGNED,
    )


def _yaml_upload(nodes=(), edges=()):
    content = yaml.safe_dump({"nodes": list(nodes), "edges": list(edges)}).encode()
    return SimpleUploadedFile("import.yaml", content, content_type="application/x-yaml")


class TestImportUploadView:
    def test_requires_login(self, graph):
        resp = Client().get(f"/export/graphs/{graph.pk}/import/")
        assert resp.status_code == 302
        assert "/accounts/login/" in resp["Location"]

    def test_admin_can_upload_and_reach_preview(self, graph, admin_user):
        client = Client()
        client.login(username="import-admin", password="pw")
        resp = client.post(
            f"/export/graphs/{graph.pk}/import/",
            {"import_file": _yaml_upload(nodes=[{"node_id": "node-a", "name": "A"}])},
        )
        assert resp.status_code == 302
        assert "/import/preview/" in resp["Location"]

    def test_annotator_with_non_editable_assignment_is_blocked(
        self, graph, assignment, annotator_user
    ):
        assignment.status = Assignment.STATUS_SUBMITTED
        assignment.save(update_fields=["status"])

        client = Client()
        client.login(username="import-annotator", password="pw")
        resp = client.get(f"/export/graphs/{graph.pk}/import/")
        assert resp.status_code == 403

    def test_annotator_with_editable_assignment_can_upload(
        self, graph, assignment, annotator_user
    ):
        client = Client()
        client.login(username="import-annotator", password="pw")
        resp = client.post(
            f"/export/graphs/{graph.pk}/import/",
            {"import_file": _yaml_upload(nodes=[{"node_id": "node-a", "name": "A"}])},
        )
        assert resp.status_code == 302
        assert "/import/preview/" in resp["Location"]

    def test_annotator_without_any_assignment_is_blocked(self, graph, annotator_user):
        client = Client()
        client.login(username="import-annotator", password="pw")
        resp = client.get(f"/export/graphs/{graph.pk}/import/")
        assert resp.status_code == 403

    def test_non_member_cannot_upload(self, graph):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user("outsider", password="pw")
        client = Client()
        client.login(username="outsider", password="pw")
        resp = client.get(f"/export/graphs/{graph.pk}/import/")
        assert resp.status_code == 403


class TestImportPreviewAndApply:
    def _preview_token(self, client, graph, nodes=(), edges=(), full_sync=False):
        data = {"import_file": _yaml_upload(nodes=nodes, edges=edges)}
        if full_sync:
            data["full_sync"] = "on"
        resp = client.post(f"/export/graphs/{graph.pk}/import/", data)
        assert resp.status_code == 302
        return resp["Location"].split("token=", 1)[1]

    def test_preview_shows_report_without_writing(self, graph, admin_user):
        client = Client()
        client.login(username="import-admin", password="pw")
        token = self._preview_token(
            client, graph, nodes=[{"node_id": "node-a", "name": "A"}]
        )

        assert not Node.objects.filter(graph=graph, node_id="node-a").exists()

        resp = client.get(f"/export/graphs/{graph.pk}/import/preview/?token={token}")
        assert resp.status_code == 200
        assert b"node-a" in resp.content
        assert not Node.objects.filter(graph=graph, node_id="node-a").exists()

    def test_apply_commits_the_plan(self, graph, admin_user):
        client = Client()
        client.login(username="import-admin", password="pw")
        token = self._preview_token(
            client, graph, nodes=[{"node_id": "node-a", "name": "A"}]
        )

        resp = client.post(f"/export/graphs/{graph.pk}/import/apply/", {"token": token})
        assert resp.status_code == 302
        assert Node.objects.filter(graph=graph, node_id="node-a").exists()

    def test_apply_with_unknown_token_redirects_to_upload(self, graph, admin_user):
        client = Client()
        client.login(username="import-admin", password="pw")
        resp = client.post(
            f"/export/graphs/{graph.pk}/import/apply/", {"token": "does-not-exist"}
        )
        assert resp.status_code == 302
        assert resp["Location"].rstrip("/").endswith("import")

    def test_double_submitted_apply_does_not_double_create(self, graph, admin_user):
        client = Client()
        client.login(username="import-admin", password="pw")
        token = self._preview_token(
            client, graph, nodes=[{"node_id": "node-a", "name": "A"}]
        )

        first = client.post(
            f"/export/graphs/{graph.pk}/import/apply/", {"token": token}
        )
        assert first.status_code == 302
        assert Node.objects.filter(graph=graph, node_id="node-a").count() == 1

        # The token is claimed (discarded) before the first apply commits,
        # so a second submission — a double-click, a retried request — must
        # find it already gone rather than racing a second create.
        second = client.post(
            f"/export/graphs/{graph.pk}/import/apply/", {"token": token}
        )
        assert second.status_code == 302
        assert Node.objects.filter(graph=graph, node_id="node-a").count() == 1

    def test_admin_can_apply_full_sync_deleting_untouched_node(self, graph, admin_user):
        create_node(graph, {"name": "Old"}, actor=admin_user, node_id="node-old")

        client = Client()
        client.login(username="import-admin", password="pw")
        token = self._preview_token(
            client, graph, nodes=[{"node_id": "node-a", "name": "A"}], full_sync=True
        )
        client.post(f"/export/graphs/{graph.pk}/import/apply/", {"token": token})

        assert Node.objects.filter(graph=graph, node_id="node-a").exists()
        assert not Node.objects.filter(graph=graph, node_id="node-old").exists()

    def test_apply_blocked_for_different_non_admin_user(
        self, graph, project, document, admin_user
    ):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user("other-annotator", password="pw")
        ProjectMembership.objects.create(project=project, user=other, role="annotator")
        Assignment.objects.create(
            project=project,
            document=document,
            graph=graph,
            annotator=other,
            assigned_by=admin_user,
            status=Assignment.STATUS_ASSIGNED,
        )

        client = Client()
        client.login(username="import-admin", password="pw")
        token = self._preview_token(
            client, graph, nodes=[{"node_id": "node-a", "name": "A"}]
        )

        other_client = Client()
        other_client.login(username="other-annotator", password="pw")
        resp = other_client.post(
            f"/export/graphs/{graph.pk}/import/apply/", {"token": token}
        )
        assert resp.status_code == 403


class TestExportExcelView:
    def test_download_current_annotations(self, graph, admin_user):
        create_node(graph, {"name": "A"}, actor=admin_user, node_id="node-a")
        client = Client()
        client.login(username="import-admin", password="pw")
        resp = client.get(f"/export/graphs/{graph.pk}/export.xlsx")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp["Content-Type"]

    def test_blank_template_has_headers_only(self, graph, admin_user):
        import openpyxl

        create_node(graph, {"name": "A"}, actor=admin_user, node_id="node-a")
        client = Client()
        client.login(username="import-admin", password="pw")
        resp = client.get(f"/export/graphs/{graph.pk}/export.xlsx?blank=1")
        workbook = openpyxl.load_workbook(io.BytesIO(resp.content))
        assert workbook["Nodes"].max_row == 1
