"""Tests for LLMMetricsView — apps/llm/views.py."""

import pytest
from django.urls import reverse

from apps.annotation.models import Edge, Node
from apps.annotation.services import create_edge, create_graph, create_node
from apps.projects.models import Document, Project, ProjectMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        "llm-metrics-admin", "llm-metrics-admin@test.example", "password"
    )


@pytest.fixture
def annotator(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user("llm-metrics-annotator", password="x")


@pytest.fixture
def project(admin_user, latest_schema):
    p = Project.objects.create(name="LLM Metrics Test Project", created_by=admin_user)
    p.active_schema = latest_schema
    p.save(update_fields=["active_schema"])
    ProjectMembership.objects.create(
        project=p, user=admin_user, role=ProjectMembership.ROLE_ADMIN
    )
    return p


@pytest.fixture
def document(project):
    return Document.objects.create(
        project=project, source=Document.SOURCE_RIS_IMPORT, title="Paper"
    )


@pytest.fixture
def graph(document, admin_user, latest_schema):
    return create_graph(document, admin_user, latest_schema)


def _make_proposed_edge(graph, order=0):
    subject = create_node(
        graph, {"name": f"Subject{order}"}, origin=Node.ORIGIN_LLM_PROPOSED
    )
    obj = create_node(
        graph, {"name": f"Object{order}"}, origin=Node.ORIGIN_LLM_PROPOSED
    )
    return create_edge(
        graph, subject, obj, {"predicate": "reduces"}, origin=Edge.ORIGIN_LLM_PROPOSED
    )


class TestLLMMetricsView:
    def test_metrics_view_returns_200(self, client, project, admin_user):
        client.force_login(admin_user)

        response = client.get(reverse("llm-metrics", args=[project.pk]))

        assert response.status_code == 200

    def test_metrics_view_shows_acceptance_rate(
        self, client, project, graph, admin_user
    ):
        accepted_edge = _make_proposed_edge(graph, order=0)
        rejected_edge = _make_proposed_edge(graph, order=1)
        client.force_login(admin_user)

        client.post(reverse("proposal-accept", args=[accepted_edge.pk]))
        client.post(reverse("proposal-reject", args=[rejected_edge.pk]))

        response = client.get(reverse("llm-metrics", args=[project.pk]))

        assert response.status_code == 200
        body = response.content.decode()
        assert "50.0%" in body

    def test_metrics_view_groups_by_document(self, client, project, graph, admin_user):
        edge = _make_proposed_edge(graph)
        client.force_login(admin_user)
        client.post(reverse("proposal-accept", args=[edge.pk]))

        response = client.get(reverse("llm-metrics", args=[project.pk]))

        assert response.status_code == 200
        assert "Paper" in response.content.decode()

    def test_metrics_view_denied_for_non_admin(self, client, project, graph, annotator):
        ProjectMembership.objects.create(
            project=project, user=annotator, role=ProjectMembership.ROLE_ANNOTATOR
        )
        client.force_login(annotator)

        response = client.get(reverse("llm-metrics", args=[project.pk]))

        assert response.status_code == 403
