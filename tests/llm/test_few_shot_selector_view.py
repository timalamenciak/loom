"""Tests for FewShotSelectorView — apps/llm/views.py."""

import pytest
from django.urls import reverse

from apps.annotation.models import Edge
from apps.annotation.services import create_edge, create_graph, create_node
from apps.llm.models import FewShotExample
from apps.projects.models import Document, Project, ProjectMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        "few-shot-selector-admin", "few-shot-selector-admin@test.example", "password"
    )


@pytest.fixture
def annotator(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        "few-shot-selector-annotator", password="x"
    )


@pytest.fixture
def project(admin_user, latest_schema):
    p = Project.objects.create(
        name="Few-Shot Selector Test Project", created_by=admin_user
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
def graph(document, admin_user, latest_schema):
    return create_graph(document, admin_user, latest_schema)


def _make_edge(graph, status, order=0):
    subject = create_node(graph, {"name": f"Subject{order}"})
    obj = create_node(graph, {"name": f"Object{order}"})
    edge = create_edge(
        graph,
        subject,
        obj,
        {"predicate": "reduces", "original_sentence": f"Sentence {order}."},
    )
    edge.status = status
    edge.save(update_fields=["status"])
    return edge


class TestFewShotSelectorViewGet:
    def test_get_lists_complete_and_gold_edges(
        self, client, project, graph, admin_user
    ):
        complete_edge = _make_edge(graph, Edge.STATUS_COMPLETE, order=0)
        gold_edge = _make_edge(graph, Edge.STATUS_GOLD, order=1)
        draft_edge = _make_edge(graph, Edge.STATUS_DRAFT, order=2)
        client.force_login(admin_user)

        response = client.get(reverse("llm-few-shot-selector", args=[project.pk]))

        assert response.status_code == 200
        body = response.content.decode()
        assert f'name="selected_{complete_edge.pk}"' in body
        assert f'name="selected_{gold_edge.pk}"' in body
        assert f'name="selected_{draft_edge.pk}"' not in body

    def test_get_pre_checks_selected_examples(self, client, project, graph, admin_user):
        edge = _make_edge(graph, Edge.STATUS_COMPLETE)
        FewShotExample.objects.create(
            project=project, edge=edge, selected_by=admin_user, label="good example"
        )
        client.force_login(admin_user)

        response = client.get(reverse("llm-few-shot-selector", args=[project.pk]))

        body = response.content.decode()
        assert f'name="selected_{edge.pk}"' in body
        assert "checked" in body
        assert 'value="good example"' in body

    def test_get_denied_for_non_admin(self, client, project, graph, annotator):
        ProjectMembership.objects.create(
            project=project, user=annotator, role=ProjectMembership.ROLE_ANNOTATOR
        )
        client.force_login(annotator)

        response = client.get(reverse("llm-few-shot-selector", args=[project.pk]))

        assert response.status_code == 403


class TestFewShotSelectorViewPost:
    def test_post_selects_edge_creates_few_shot_example(
        self, client, project, graph, admin_user
    ):
        edge = _make_edge(graph, Edge.STATUS_COMPLETE)
        client.force_login(admin_user)

        response = client.post(
            reverse("llm-few-shot-selector", args=[project.pk]),
            {f"selected_{edge.pk}": "on", f"label_{edge.pk}": "strong effect"},
        )

        assert response.status_code == 302
        example = FewShotExample.objects.get(project=project, edge=edge)
        assert example.label == "strong effect"
        assert example.selected_by == admin_user

    def test_post_deselecting_removes_few_shot_example(
        self, client, project, graph, admin_user
    ):
        edge = _make_edge(graph, Edge.STATUS_COMPLETE)
        FewShotExample.objects.create(project=project, edge=edge)
        client.force_login(admin_user)

        response = client.post(reverse("llm-few-shot-selector", args=[project.pk]), {})

        assert response.status_code == 302
        assert not FewShotExample.objects.filter(project=project, edge=edge).exists()

    def test_post_denied_for_non_admin(self, client, project, graph, annotator):
        edge = _make_edge(graph, Edge.STATUS_COMPLETE)
        ProjectMembership.objects.create(
            project=project, user=annotator, role=ProjectMembership.ROLE_ANNOTATOR
        )
        client.force_login(annotator)

        response = client.post(
            reverse("llm-few-shot-selector", args=[project.pk]),
            {f"selected_{edge.pk}": "on"},
        )

        assert response.status_code == 403
        assert not FewShotExample.objects.filter(project=project, edge=edge).exists()
