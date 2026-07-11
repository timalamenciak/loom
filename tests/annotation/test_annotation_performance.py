"""Query-count regression tests for the annotation workspace and the LLM
review queue — catches N+1 queries before they ship. See
docs/performance-review-v1.0.md for the full sanity-check writeup.
"""

import pytest
from django.urls import reverse

from apps.annotation.models import Edge, Node
from apps.annotation.services import create_edge, create_graph, create_node
from apps.projects.models import Document, Project, ProjectMembership
from apps.projects.services import assign_document

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        "perf-admin", "perf-admin@test.example", "password"
    )


@pytest.fixture
def annotator(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user("perf-annotator", password="x")


@pytest.fixture
def project(admin_user, latest_schema):
    return Project.objects.create(
        name="Perf Test Project", created_by=admin_user, active_schema=latest_schema
    )


@pytest.fixture
def document(project):
    return Document.objects.create(
        project=project,
        source=Document.SOURCE_MANUAL,
        title="Perf Doc",
        canonical_text="Some annotatable text. " * 50,
    )


@pytest.fixture
def assignment(project, document, annotator, admin_user):
    ProjectMembership.objects.create(
        project=project, user=annotator, role=ProjectMembership.ROLE_ANNOTATOR
    )
    return assign_document(project, document, annotator, admin_user)


@pytest.fixture
def graph_with_10_edges(document, annotator, latest_schema, assignment):
    graph = create_graph(document, annotator, latest_schema)
    for i in range(10):
        subject = create_node(graph, {"name": f"Subject{i}"}, actor=annotator)
        obj = create_node(graph, {"name": f"Object{i}"}, actor=annotator)
        create_edge(graph, subject, obj, {}, actor=annotator)
    assignment.graph = graph
    assignment.save(update_fields=["graph"])
    return graph


class TestAnnotationPageQueryCount:
    def test_annotation_page_load_query_count(
        self,
        client,
        project,
        document,
        annotator,
        graph_with_10_edges,
        django_assert_max_num_queries,
    ):
        client.force_login(annotator)

        with django_assert_max_num_queries(20):
            response = client.get(
                reverse("annotate", kwargs={"pk": project.pk, "doc_pk": document.pk})
            )

        assert response.status_code == 200
        assert Edge.objects.filter(graph=graph_with_10_edges).count() == 10
        assert Node.objects.filter(graph=graph_with_10_edges).count() == 20


@pytest.fixture
def project_with_50_draft_proposals(admin_user, annotator, latest_schema):
    project = Project.objects.create(
        name="Perf Review Queue Project",
        created_by=admin_user,
        active_schema=latest_schema,
    )
    ProjectMembership.objects.create(
        project=project, user=admin_user, role=ProjectMembership.ROLE_ADMIN
    )
    document = Document.objects.create(
        project=project,
        source=Document.SOURCE_MANUAL,
        title="Perf Review Doc",
        canonical_text="Text.",
    )
    graph = create_graph(document, admin_user, latest_schema)
    for i in range(50):
        subject = create_node(
            graph, {"name": f"Subject{i}"}, origin=Node.ORIGIN_LLM_PROPOSED
        )
        obj = create_node(
            graph, {"name": f"Object{i}"}, origin=Node.ORIGIN_LLM_PROPOSED
        )
        create_edge(
            graph,
            subject,
            obj,
            {"predicate": "reduces", "original_sentence": f"Sentence {i}."},
            origin=Edge.ORIGIN_LLM_PROPOSED,
        )
    return project


class TestProposalReviewQueueQueryCount:
    def test_review_queue_query_count(
        self,
        client,
        admin_user,
        project_with_50_draft_proposals,
        django_assert_max_num_queries,
    ):
        client.force_login(admin_user)
        project = project_with_50_draft_proposals

        with django_assert_max_num_queries(9):
            response = client.get(reverse("proposal-review", args=[project.pk]))

        assert response.status_code == 200
        assert (
            Edge.objects.filter(
                graph__document__project=project, origin=Edge.ORIGIN_LLM_PROPOSED
            ).count()
            == 50
        )
