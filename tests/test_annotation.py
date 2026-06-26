"""
Phase 5 tests: WorkSession model, session timer service, annotation views.

Pure-Python tests (no DB) cover service helpers.
DB tests cover session open/close, heartbeat accumulation, node/edge create,
submit flow, and assignment status transitions.
"""

import json

import pytest

# ---------------------------------------------------------------------------
# Pure-Python tests (no DB)
# ---------------------------------------------------------------------------


class TestUnflattenPost:
    def test_flat(self):
        from apps.annotation.services import _unflatten_post

        data = {"predicate": "positive", "claim_strength": "causal"}
        assert _unflatten_post(data) == data

    def test_nested(self):
        from apps.annotation.services import _unflatten_post

        data = {"mediation__has_mediator": "true", "predicate": "positive"}
        result = _unflatten_post(data)
        assert result["predicate"] == "positive"
        assert result["mediation"] == {"has_mediator": "true"}

    def test_empty(self):
        from apps.annotation.services import _unflatten_post

        assert _unflatten_post({}) == {}


class TestDictGetFilter:
    def test_simple_key(self):
        from apps.annotation.templatetags.annotation_extras import dict_get

        d = {"predicate": "positive"}
        assert dict_get(d, "predicate") == "positive"

    def test_missing_key(self):
        from apps.annotation.templatetags.annotation_extras import dict_get

        assert dict_get({"a": 1}, "b") == ""

    def test_nested_key(self):
        from apps.annotation.templatetags.annotation_extras import dict_get

        d = {"mediation": {"has_mediator": "true"}}
        assert dict_get(d, "mediation__has_mediator") == "true"

    def test_non_dict_returns_empty(self):
        from apps.annotation.templatetags.annotation_extras import dict_get

        assert dict_get("not a dict", "key") == ""
        assert dict_get(None, "key") == ""

    def test_nested_missing(self):
        from apps.annotation.templatetags.annotation_extras import dict_get

        d = {"mediation": {"has_mediator": "true"}}
        assert dict_get(d, "mediation__other") == ""


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_and_user(db):
    from django.contrib.auth import get_user_model

    from apps.projects.models import Project, ProjectMembership

    User = get_user_model()
    user = User.objects.create_user("annotator1", password="pw")
    project = Project.objects.create(name="Test Project", created_by=user)
    ProjectMembership.objects.create(project=project, user=user, role="annotator")
    return project, user


@pytest.fixture
def schema_version(db):
    """Load the CAMO schema so tests can create graphs."""
    from pathlib import Path

    from apps.schemas.models import SchemaVersion

    schema_path = (
        Path(__file__).resolve().parent.parent / "config" / "schema" / "camo-0.4.0.yaml"
    )
    if not schema_path.exists():
        pytest.skip("CAMO schema file not found — skipping DB annotation tests")

    sv = SchemaVersion.objects.create(
        version="0.4.0",
        linkml_yaml=schema_path.read_text(encoding="utf-8"),
        is_active=True,
    )
    return sv


@pytest.fixture
def document(project_and_user):
    project, user = project_and_user
    from apps.projects.models import Document

    return Document.objects.create(
        project=project,
        source="manual",
        title="Buckthorn invasion drives nitrogen cycling",
        canonical_text="Rhamnus cathartica increases soil nitrogen availability.",
    )


@pytest.fixture
def assignment(project_and_user, document):
    project, user = project_and_user
    from apps.projects.models import Assignment

    return Assignment.objects.create(
        project=project,
        document=document,
        annotator=user,
        assigned_by=user,
        status=Assignment.STATUS_ASSIGNED,
    )


@pytest.fixture
def graph(project_and_user, document, schema_version):
    project, user = project_and_user
    from apps.annotation.models import CausalGraph

    return CausalGraph.objects.create(
        document=document,
        annotator=user,
        schema_version=schema_version,
    )


# ---------------------------------------------------------------------------
# WorkSession model tests
# ---------------------------------------------------------------------------


class TestWorkSessionModel:
    def test_create_session(self, assignment, project_and_user):
        from apps.annotation.models import WorkSession

        _, user = project_and_user
        session = WorkSession.objects.create(assignment=assignment, annotator=user)
        assert session.active_seconds == 0
        assert session.ended_at is None
        assert str(user.username) in str(session)

    def test_open_session_creates(self, assignment, project_and_user):
        from apps.annotation.services import open_session

        _, user = project_and_user
        session = open_session(assignment, user)
        assert session.pk is not None
        assert session.ended_at is None

    def test_open_session_reuses(self, assignment, project_and_user):
        from apps.annotation.services import open_session

        _, user = project_and_user
        s1 = open_session(assignment, user)
        s2 = open_session(assignment, user)
        assert s1.pk == s2.pk

    def test_heartbeat_accumulates(self, assignment, project_and_user):
        from apps.annotation.services import heartbeat, open_session

        _, user = project_and_user
        session = open_session(assignment, user)
        heartbeat(session, active_delta=15, idle_delta=0)
        heartbeat(session, active_delta=10, idle_delta=5)
        assert session.active_seconds == 25
        assert session.idle_seconds == 5

    def test_close_session(self, assignment, project_and_user):
        from apps.annotation.services import close_session, open_session

        _, user = project_and_user
        session = open_session(assignment, user)
        close_session(session)
        assert session.ended_at is not None
        assert session.open_seconds >= 0

    def test_close_session_sets_open_seconds(self, assignment, project_and_user):
        from apps.annotation.services import close_session, heartbeat, open_session

        _, user = project_and_user
        session = open_session(assignment, user)
        heartbeat(session, 30, 0)
        close_session(session)
        assert session.active_seconds == 30
        assert session.open_seconds >= 0


# ---------------------------------------------------------------------------
# Annotation view tests
# ---------------------------------------------------------------------------


class TestAnnotationView:
    def test_requires_login(self, document, client):
        url = f"/annotation/1/documents/{document.pk}/annotate/"
        resp = client.get(url)
        assert resp.status_code == 302
        assert "/accounts/login/" in resp["Location"]

    def test_non_member_forbidden(self, project_and_user, document, schema_version, db):
        from django.contrib.auth import get_user_model
        from django.test import Client

        User = get_user_model()
        outsider = User.objects.create_user("outsider", password="pw")
        client = Client()
        client.login(username="outsider", password="pw")
        project, _ = project_and_user
        url = f"/annotation/{project.pk}/documents/{document.pk}/annotate/"
        resp = client.get(url)
        assert resp.status_code == 403

    def test_get_creates_graph_and_advances_assignment(
        self, project_and_user, document, assignment, schema_version
    ):
        from django.test import Client

        from apps.annotation.models import CausalGraph
        from apps.projects.models import Assignment

        project, user = project_and_user
        client = Client()
        client.login(username=user.username, password="pw")
        url = f"/annotation/{project.pk}/documents/{document.pk}/annotate/"
        resp = client.get(url)
        assert resp.status_code == 200

        # Graph created
        assert CausalGraph.objects.filter(document=document, annotator=user).exists()

        # Assignment advanced
        assignment.refresh_from_db()
        assert assignment.status == Assignment.STATUS_IN_PROGRESS

    def test_get_opens_session(
        self, project_and_user, document, assignment, schema_version
    ):
        from django.test import Client

        from apps.annotation.models import WorkSession

        project, user = project_and_user
        client = Client()
        client.login(username=user.username, password="pw")
        url = f"/annotation/{project.pk}/documents/{document.pk}/annotate/"
        client.get(url)
        assert WorkSession.objects.filter(assignment=assignment).exists()

    def test_get_handles_duplicate_existing_graphs(
        self, project_and_user, document, assignment, schema_version
    ):
        from django.test import Client

        from apps.annotation.models import CausalGraph

        project, user = project_and_user
        graph1 = CausalGraph.objects.create(
            document=document,
            annotator=user,
            schema_version=schema_version,
        )
        graph2 = CausalGraph.objects.create(
            document=document,
            annotator=user,
            schema_version=schema_version,
        )
        client = Client()
        client.login(username=user.username, password="pw")

        url = f"/annotation/{project.pk}/documents/{document.pk}/annotate/"
        resp = client.get(url)

        assert resp.status_code == 200
        assert CausalGraph.objects.filter(document=document, annotator=user).count() == 2
        assignment.refresh_from_db()
        assert assignment.graph_id in {graph1.pk, graph2.pk}


# ---------------------------------------------------------------------------
# Node / Edge CRUD tests
# ---------------------------------------------------------------------------


class TestNodeCreate:
    def test_create_node_htmx(
        self, project_and_user, document, assignment, graph, schema_version
    ):
        from django.test import Client

        from apps.annotation.models import Node

        project, user = project_and_user
        client = Client()
        client.login(username=user.username, password="pw")
        url = f"/annotation/{project.pk}/documents/{document.pk}/annotate/nodes/"
        resp = client.post(
            url,
            {"entity_type": "biotic", "entity_term": "NCBITaxon:712036", "direction": "increases"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        assert Node.objects.filter(graph=graph).exists()
        node = Node.objects.filter(graph=graph).first()
        assert node.data.get("entity_type") == "biotic"


class TestEdgeCreate:
    def test_create_edge_htmx(
        self, project_and_user, document, assignment, graph, schema_version
    ):
        from django.test import Client

        from apps.annotation.models import Edge, Node

        project, user = project_and_user
        client = Client()
        client.login(username=user.username, password="pw")

        # Create two nodes first
        node_a = Node.objects.create(
            graph=graph,
            name="Soil N",
            data={"entity_type": "abiotic"},
            schema_version=schema_version,
        )
        node_b = Node.objects.create(
            graph=graph,
            name="Plant biomass",
            data={"entity_type": "biotic"},
            schema_version=schema_version,
        )

        url = f"/annotation/{project.pk}/documents/{document.pk}/annotate/edges/"
        resp = client.post(
            url,
            {
                "subject": node_a.node_id,
                "object": node_b.node_id,
                "predicate": "positive",
                "claim_strength": "causal",
            },
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        assert Edge.objects.filter(graph=graph).exists()
        edge = Edge.objects.filter(graph=graph).first()
        assert edge.subject == node_a
        assert edge.predicate == "positive"

    def test_edge_missing_nodes_returns_400(
        self, project_and_user, document, graph, schema_version
    ):
        from django.test import Client

        project, user = project_and_user
        client = Client()
        client.login(username=user.username, password="pw")
        url = f"/annotation/{project.pk}/documents/{document.pk}/annotate/edges/"
        resp = client.post(url, {"predicate": "positive"}, HTTP_HX_REQUEST="true")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Heartbeat tests
# ---------------------------------------------------------------------------


class TestHeartbeat:
    def test_heartbeat_accumulates(
        self, project_and_user, document, assignment, schema_version
    ):
        from django.test import Client

        from apps.annotation.models import WorkSession
        from apps.annotation.services import open_session

        project, user = project_and_user
        session = open_session(assignment, user)

        client = Client()
        client.login(username=user.username, password="pw")
        url = f"/annotation/sessions/{session.pk}/heartbeat/"
        resp = client.post(
            url,
            json.dumps({"active_delta": 15, "idle_delta": 0}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["active_seconds"] == 15

        # Second heartbeat accumulates
        client.post(
            url,
            json.dumps({"active_delta": 10, "idle_delta": 5}),
            content_type="application/json",
        )
        session.refresh_from_db()
        assert session.active_seconds == 25
        assert session.idle_seconds == 5

    def test_heartbeat_with_ended_closes_session(
        self, project_and_user, document, assignment, schema_version
    ):
        from django.test import Client

        from apps.annotation.models import WorkSession
        from apps.annotation.services import open_session

        project, user = project_and_user
        session = open_session(assignment, user)

        client = Client()
        client.login(username=user.username, password="pw")
        url = f"/annotation/sessions/{session.pk}/heartbeat/"
        client.post(
            url,
            json.dumps({"active_delta": 20, "idle_delta": 0, "ended": True}),
            content_type="application/json",
        )
        session.refresh_from_db()
        assert session.ended_at is not None
        assert session.active_seconds == 20


# ---------------------------------------------------------------------------
# Submit flow tests (Phase 5 acceptance criterion)
# ---------------------------------------------------------------------------


class TestSubmitAnnotation:
    def test_submit_advances_status_and_closes_sessions(
        self, project_and_user, document, assignment, graph, schema_version
    ):
        from django.test import Client

        from apps.annotation.models import WorkSession
        from apps.annotation.services import open_session
        from apps.projects.models import Assignment

        project, user = project_and_user
        session = open_session(assignment, user)

        client = Client()
        client.login(username=user.username, password="pw")
        url = f"/annotation/{project.pk}/documents/{document.pk}/annotate/submit/"
        resp = client.post(url)

        # Redirects to queue
        assert resp.status_code == 302
        assert "queue" in resp["Location"]

        # Assignment submitted
        assignment.refresh_from_db()
        assert assignment.status == Assignment.STATUS_SUBMITTED

        # Session closed
        session.refresh_from_db()
        assert session.ended_at is not None

    def test_active_seconds_recorded(
        self, project_and_user, document, assignment, graph, schema_version
    ):
        from django.test import Client

        from apps.annotation.models import WorkSession
        from apps.annotation.services import heartbeat, open_session

        project, user = project_and_user
        session = open_session(assignment, user)
        heartbeat(session, active_delta=120, idle_delta=10)

        client = Client()
        client.login(username=user.username, password="pw")
        url = f"/annotation/{project.pk}/documents/{document.pk}/annotate/submit/"
        client.post(url)

        session.refresh_from_db()
        assert session.active_seconds == 120  # preserved after close
