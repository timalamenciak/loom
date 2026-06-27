"""
Phase 7 tests: adjudication, time-on-task CSV, IRR export, migrate_graph diff.

Pure-Python tests cover adjudicate_edge service and the schema-diff helpers.
DB tests cover the full reviewer flow and CSV exports.
"""

from pathlib import Path

import pytest

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "schema" / "camo-0.4.0.yaml"
)


# ── Pure-Python: adjudication service ────────────────────────────────────────


class TestAdjudicateEdge:
    def _make_edge(self, status):
        """Return a minimal mock edge with the given status."""
        from unittest.mock import MagicMock

        from apps.annotation.models import Edge

        edge = MagicMock(spec=Edge)
        edge.status = status
        edge.STATUS_DRAFT = Edge.STATUS_DRAFT
        edge.STATUS_COMPLETE = Edge.STATUS_COMPLETE
        edge.STATUS_REVIEWED = Edge.STATUS_REVIEWED
        edge.STATUS_GOLD = Edge.STATUS_GOLD
        return edge

    def test_complete_advances_to_reviewed(self):
        from apps.annotation.models import Edge
        from apps.annotation.services import adjudicate_edge

        edge = self._make_edge(Edge.STATUS_COMPLETE)
        adjudicate_edge(edge, actor=None)
        edge.save.assert_called_once()
        assert edge.status == Edge.STATUS_REVIEWED

    def test_reviewed_advances_to_gold(self):
        from apps.annotation.models import Edge
        from apps.annotation.services import adjudicate_edge

        edge = self._make_edge(Edge.STATUS_REVIEWED)
        adjudicate_edge(edge, actor=None)
        assert edge.status == Edge.STATUS_GOLD

    def test_draft_not_adjudicatable(self):
        from apps.annotation.models import Edge
        from apps.annotation.services import adjudicate_edge

        edge = self._make_edge(Edge.STATUS_DRAFT)
        adjudicate_edge(edge, actor=None)
        edge.save.assert_not_called()
        assert edge.status == Edge.STATUS_DRAFT

    def test_gold_is_terminal(self):
        from apps.annotation.models import Edge
        from apps.annotation.services import adjudicate_edge

        edge = self._make_edge(Edge.STATUS_GOLD)
        adjudicate_edge(edge, actor=None)
        edge.save.assert_not_called()
        assert edge.status == Edge.STATUS_GOLD


# ── Pure-Python: migrate_graph schema-diff helpers ────────────────────────────


class TestSchemaDiff:
    def _sv_stub(self, yaml_text):
        from unittest.mock import MagicMock

        sv = MagicMock()
        sv.linkml_yaml = yaml_text
        return sv

    def _slot_names(self, sv):
        from apps.export.management.commands.migrate_graph import _slot_names

        return _slot_names(sv)

    def _enum_values(self, sv):
        from apps.export.management.commands.migrate_graph import _enum_values

        return _enum_values(sv)

    def test_slot_names_from_real_schema(self):
        if not SCHEMA_PATH.exists():
            pytest.skip("CAMO schema not found")
        sv = self._sv_stub(SCHEMA_PATH.read_text(encoding="utf-8"))
        slots = self._slot_names(sv)
        assert "predicate" in slots
        assert "claim_strength" in slots
        assert "entity_type" in slots

    def test_enum_values_from_real_schema(self):
        if not SCHEMA_PATH.exists():
            pytest.skip("CAMO schema not found")
        sv = self._sv_stub(SCHEMA_PATH.read_text(encoding="utf-8"))
        enums = self._enum_values(sv)
        assert "PredicateEnum" in enums
        assert "positively_regulates" in enums["PredicateEnum"]

    def test_has_value_flat(self):
        from apps.export.management.commands.migrate_graph import _has_value

        assert _has_value({"predicate": "pos"}, "predicate") is True
        assert _has_value({"predicate": ""}, "predicate") is False
        assert _has_value({}, "predicate") is False

    def test_has_value_nested(self):
        from apps.export.management.commands.migrate_graph import _has_value

        data = {"mediation": {"has_mediator": "yes"}}
        assert _has_value(data, "mediation__has_mediator") is True
        assert _has_value(data, "mediation__mediator_notes") is False


def test_audit_admin_is_append_only():
    from django.contrib.admin.sites import AdminSite

    from apps.audit.admin import AuditEventAdmin
    from apps.audit.models import AuditEvent

    admin = AuditEventAdmin(AuditEvent, AdminSite())
    assert admin.has_add_permission(None) is False
    assert admin.has_change_permission(None) is False
    assert admin.has_delete_permission(None) is False


# ── DB fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def project_with_roles(db):
    from django.contrib.auth import get_user_model

    from apps.projects.models import Project, ProjectMembership

    User = get_user_model()
    admin = User.objects.create_user("admin_u", password="pw")
    annotator = User.objects.create_user("annotator_u", password="pw")
    reviewer = User.objects.create_user("reviewer_u", password="pw")

    project = Project.objects.create(name="Review Test Project", created_by=admin)
    ProjectMembership.objects.create(project=project, user=admin, role="admin")
    ProjectMembership.objects.create(project=project, user=annotator, role="annotator")
    ProjectMembership.objects.create(project=project, user=reviewer, role="reviewer")
    return project, admin, annotator, reviewer


@pytest.fixture
def schema_version(db):
    from apps.schemas.models import SchemaVersion

    if not SCHEMA_PATH.exists():
        pytest.skip("CAMO schema not found")
    return SchemaVersion.objects.create(
        version="0.4.0",
        linkml_yaml=SCHEMA_PATH.read_text(encoding="utf-8"),
        is_active=True,
    )


@pytest.fixture
def submitted_graph(project_with_roles, schema_version):
    from apps.annotation.models import CausalGraph, Edge, Node
    from apps.projects.models import Assignment, Document

    project, admin, annotator, reviewer = project_with_roles
    doc = Document.objects.create(
        project=project,
        source="manual",
        title="Buckthorn paper",
        canonical_text="Rhamnus cathartica increases soil N.",
    )
    assignment = Assignment.objects.create(
        project=project,
        document=doc,
        annotator=annotator,
        assigned_by=admin,
        status=Assignment.STATUS_SUBMITTED,
    )
    graph = CausalGraph.objects.create(
        document=doc,
        annotator=annotator,
        schema_version=schema_version,
    )
    assignment.graph = graph
    assignment.save(update_fields=["graph"])

    node_a = Node.objects.create(
        graph=graph,
        node_id="na",
        name="Buckthorn",
        data={"entity_type": "biotic"},
        schema_version=schema_version,
    )
    node_b = Node.objects.create(
        graph=graph,
        node_id="nb",
        name="Soil N",
        data={"entity_type": "abiotic"},
        schema_version=schema_version,
    )
    edge = Edge.objects.create(
        graph=graph,
        edge_id="e1",
        subject=node_a,
        object=node_b,
        predicate="positively_regulates",
        claim_strength="tendency",
        status=Edge.STATUS_COMPLETE,
        data={"philosophical_account": "mechanistic", "certainty_grade": "0.8"},
        schema_version=schema_version,
    )
    return project, admin, annotator, reviewer, doc, assignment, graph, edge


# ── DB: adjudication flow ─────────────────────────────────────────────────────


class TestAdjudicateEdgeDB:
    def test_reviewer_can_mark_reviewed(self, submitted_graph):
        from django.test import Client

        from apps.annotation.models import Edge

        project, admin, annotator, reviewer, doc, assignment, graph, edge = (
            submitted_graph
        )
        client = Client()
        client.login(username="reviewer_u", password="pw")
        url = f"/annotation/{project.pk}/documents/{doc.pk}/review/graphs/{graph.pk}/edges/{edge.pk}/adjudicate/"
        resp = client.post(url)
        assert resp.status_code == 302
        edge.refresh_from_db()
        assert edge.status == Edge.STATUS_REVIEWED

    def test_admin_can_mark_gold_from_reviewed(self, submitted_graph):
        from django.test import Client

        from apps.annotation.models import Edge
        from apps.annotation.services import adjudicate_edge

        project, admin, annotator, reviewer, doc, assignment, graph, edge = (
            submitted_graph
        )
        # First advance to reviewed
        adjudicate_edge(edge, reviewer)

        client = Client()
        client.login(username="admin_u", password="pw")
        url = f"/annotation/{project.pk}/documents/{doc.pk}/review/graphs/{graph.pk}/edges/{edge.pk}/adjudicate/"
        resp = client.post(url)
        assert resp.status_code == 302
        edge.refresh_from_db()
        assert edge.status == Edge.STATUS_GOLD

    def test_annotator_cannot_adjudicate(self, submitted_graph):
        from django.test import Client

        project, admin, annotator, reviewer, doc, assignment, graph, edge = (
            submitted_graph
        )
        client = Client()
        client.login(username="annotator_u", password="pw")
        url = f"/annotation/{project.pk}/documents/{doc.pk}/review/graphs/{graph.pk}/edges/{edge.pk}/adjudicate/"
        resp = client.post(url)
        assert resp.status_code == 403

    def test_review_document_view(self, submitted_graph):
        from django.test import Client

        project, admin, annotator, reviewer, doc, assignment, graph, edge = (
            submitted_graph
        )
        client = Client()
        client.login(username="reviewer_u", password="pw")
        resp = client.get(f"/annotation/{project.pk}/documents/{doc.pk}/review/")
        assert resp.status_code == 200
        assert b"Buckthorn" in resp.content


# ── DB: time-on-task CSV ──────────────────────────────────────────────────────


class TestTimeReport:
    def test_csv_format(self, submitted_graph):
        from django.test import Client

        from apps.annotation.models import WorkSession

        project, admin, annotator, reviewer, doc, assignment, graph, edge = (
            submitted_graph
        )

        # Create a session with known active time
        WorkSession.objects.create(
            assignment=assignment,
            annotator=annotator,
            active_seconds=300,
            open_seconds=360,
        )

        client = Client()
        client.login(username="admin_u", password="pw")
        resp = client.get(f"/projects/{project.pk}/time-report.csv")
        assert resp.status_code == 200
        assert "text/csv" in resp["Content-Type"]

        lines = resp.content.decode().splitlines()
        header = lines[0].split(",")
        assert "document_id" in header
        assert "active_seconds" in header
        assert "active_minutes" in header

        # Data row exists
        assert len(lines) >= 2

    def test_non_admin_cannot_download(self, submitted_graph):
        from django.test import Client

        project, admin, annotator, reviewer, doc, assignment, graph, edge = (
            submitted_graph
        )
        client = Client()
        client.login(username="annotator_u", password="pw")
        resp = client.get(f"/projects/{project.pk}/time-report.csv")
        assert resp.status_code == 403


# ── DB: IRR CSV ───────────────────────────────────────────────────────────────


class TestIRRExport:
    def test_csv_contains_edge_data(self, submitted_graph):
        from django.test import Client

        project, admin, annotator, reviewer, doc, assignment, graph, edge = (
            submitted_graph
        )
        client = Client()
        client.login(username="admin_u", password="pw")
        resp = client.get(f"/projects/{project.pk}/irr-export.csv")
        assert resp.status_code == 200
        assert "text/csv" in resp["Content-Type"]

        content = resp.content.decode()
        assert "document_id" in content
        assert "predicate" in content
        assert "positively_regulates" in content
        assert "mechanistic" in content

    def test_non_admin_cannot_download(self, submitted_graph):
        from django.test import Client

        project, admin, annotator, reviewer, doc, assignment, graph, edge = (
            submitted_graph
        )
        client = Client()
        client.login(username="annotator_u", password="pw")
        resp = client.get(f"/projects/{project.pk}/irr-export.csv")
        assert resp.status_code == 403
