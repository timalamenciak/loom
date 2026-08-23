"""Tests for FewShotExample.clean() — only complete/gold edges may be used as
few-shot examples in the LLM proposal prompt.
"""

import pytest
from django.core.exceptions import ValidationError

from apps.annotation.models import Edge
from apps.annotation.services import create_edge, create_graph, create_node
from apps.llm.models import FewShotExample
from apps.projects.models import Document, Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        "few-shot-admin", "few-shot-admin@test.example", "password"
    )


@pytest.fixture
def project(admin_user, latest_schema):
    p = Project.objects.create(name="Few-Shot Test Project", created_by=admin_user)
    p.active_schema = latest_schema
    p.save(update_fields=["active_schema"])
    return p


@pytest.fixture
def document(project):
    return Document.objects.create(
        project=project, source=Document.SOURCE_RIS_IMPORT, title="Paper"
    )


@pytest.fixture
def graph(document, admin_user, latest_schema):
    return create_graph(document, admin_user, latest_schema)


def _make_edge(graph, status):
    subject = create_node(graph, {"name": "Wolves"})
    obj = create_node(graph, {"name": "Deer"})
    edge = create_edge(graph, subject, obj, {"predicate": "reduces"})
    edge.status = status
    edge.save(update_fields=["status"])
    return edge


class TestFewShotExampleClean:
    def test_clean_passes_for_complete_edge(self, project, graph):
        edge = _make_edge(graph, Edge.STATUS_COMPLETE)
        example = FewShotExample(project=project, edge=edge)
        example.clean()

    def test_clean_passes_for_gold_edge(self, project, graph):
        edge = _make_edge(graph, Edge.STATUS_GOLD)
        example = FewShotExample(project=project, edge=edge)
        example.clean()

    def test_clean_fails_for_draft_edge(self, project, graph):
        edge = _make_edge(graph, Edge.STATUS_DRAFT)
        example = FewShotExample(project=project, edge=edge)
        with pytest.raises(ValidationError) as exc_info:
            example.clean()
        assert "edge" in exc_info.value.error_dict

    def test_clean_fails_for_reviewed_edge(self, project, graph):
        edge = _make_edge(graph, Edge.STATUS_REVIEWED)
        example = FewShotExample(project=project, edge=edge)
        with pytest.raises(ValidationError) as exc_info:
            example.clean()
        assert "edge" in exc_info.value.error_dict
