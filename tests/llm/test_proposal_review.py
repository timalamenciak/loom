"""Tests for the LLM proposal review queue — apps/llm/views.py."""

import pytest
from django.urls import reverse

from apps.annotation.models import Edge, Node
from apps.annotation.services import create_edge, create_graph, create_node
from apps.projects.models import Assignment, Document, Project, ProjectMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        "proposal-review-admin", "proposal-review-admin@test.example", "password"
    )


@pytest.fixture
def annotator(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        "proposal-review-annotator", password="x"
    )


@pytest.fixture
def project(admin_user, latest_schema):
    p = Project.objects.create(
        name="Proposal Review Test Project", created_by=admin_user
    )
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
def assignment(project, document, annotator, admin_user):
    ProjectMembership.objects.create(
        project=project, user=annotator, role=ProjectMembership.ROLE_ANNOTATOR
    )
    return Assignment.objects.create(
        project=project,
        document=document,
        annotator=annotator,
        assigned_by=admin_user,
        status=Assignment.STATUS_ASSIGNED,
    )


@pytest.fixture
def graph(document, annotator, latest_schema, assignment):
    return create_graph(document, annotator, latest_schema)


def _make_proposed_edge(graph, status=Edge.STATUS_DRAFT):
    subject = create_node(graph, {"name": "Wolves"}, origin=Node.ORIGIN_LLM_PROPOSED)
    obj = create_node(graph, {"name": "Deer"}, origin=Node.ORIGIN_LLM_PROPOSED)
    edge = create_edge(
        graph,
        subject,
        obj,
        {"predicate": "reduces", "original_sentence": "Wolves reduce deer."},
        origin=Edge.ORIGIN_LLM_PROPOSED,
    )
    if status != Edge.STATUS_DRAFT:
        edge.status = status
        edge.save(update_fields=["status"])
    return edge


class TestProposalReviewView:
    def test_review_shows_draft_proposals(self, client, project, graph, assignment):
        edge = _make_proposed_edge(graph)
        client.force_login(assignment.annotator)

        response = client.get(reverse("proposal-review", args=[project.pk]))

        assert response.status_code == 200
        assert f"proposal-{edge.pk}" in response.content.decode()

    def test_complete_edges_not_shown(self, client, project, graph, assignment):
        edge = _make_proposed_edge(graph, status=Edge.STATUS_COMPLETE)
        client.force_login(assignment.annotator)

        response = client.get(reverse("proposal-review", args=[project.pk]))

        assert f"proposal-{edge.pk}" not in response.content.decode()

    def test_access_denied_for_unassigned_user(self, client, project, graph):
        from django.contrib.auth import get_user_model

        unassigned = get_user_model().objects.create_user(
            "proposal-review-unassigned", password="x"
        )
        ProjectMembership.objects.create(
            project=project, user=unassigned, role=ProjectMembership.ROLE_ANNOTATOR
        )
        client.force_login(unassigned)

        response = client.get(reverse("proposal-review", args=[project.pk]))

        assert response.status_code == 403


class TestProposalActions:
    def test_accept_advances_status(self, client, project, graph, assignment):
        edge = _make_proposed_edge(graph)
        client.force_login(assignment.annotator)

        response = client.post(reverse("proposal-accept", args=[edge.pk]))

        assert response.status_code == 200
        edge.refresh_from_db()
        assert edge.status == Edge.STATUS_COMPLETE

    def test_reject_deletes(self, client, project, graph, assignment):
        edge = _make_proposed_edge(graph)
        client.force_login(assignment.annotator)

        response = client.post(reverse("proposal-reject", args=[edge.pk]))

        assert response.status_code == 200
        assert not Edge.objects.filter(pk=edge.pk).exists()
