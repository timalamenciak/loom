"""Query-count regression test for apps/export/serializer.py — catches N+1
queries on per-edge relations (e.g. source_spans). See
docs/performance-review-v1.0.md for the full sanity-check writeup.
"""

import pytest

from apps.annotation.services import (
    create_edge,
    create_graph,
    create_node,
    set_edge_source_spans,
)
from apps.documents.services import create_span
from apps.export.serializer import serialize_graph
from apps.projects.models import Document, Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        "export-perf-admin", "export-perf-admin@test.example", "password"
    )


@pytest.fixture
def project(admin_user, latest_schema):
    return Project.objects.create(
        name="Export Perf Project", created_by=admin_user, active_schema=latest_schema
    )


@pytest.fixture
def document(project):
    return Document.objects.create(
        project=project,
        source=Document.SOURCE_MANUAL,
        title="Export Perf Doc",
        canonical_text="Wolves reduce deer populations in Yellowstone. " * 20,
    )


@pytest.fixture
def graph_with_50_edges(document, admin_user, latest_schema):
    graph = create_graph(document, admin_user, latest_schema)
    for i in range(50):
        subject = create_node(graph, {"name": f"Subject{i}"}, actor=admin_user)
        obj = create_node(graph, {"name": f"Object{i}"}, actor=admin_user)
        edge = create_edge(graph, subject, obj, {}, actor=admin_user)
        # Every other edge gets a grounding span, so the query-count test
        # actually exercises the edge->spans relation instead of always
        # hitting an empty prefetch.
        if i % 2 == 0:
            span = create_span(
                document=document,
                start_char=0,
                end_char=10,
                created_by=admin_user,
                text_source="canonical_text",
            )
            set_edge_source_spans(edge, [span], admin_user)
    return graph


class TestSerializeGraphQueryCount:
    def test_serialize_graph_query_count(
        self, graph_with_50_edges, django_assert_max_num_queries
    ):
        with django_assert_max_num_queries(19):
            data = serialize_graph(graph_with_50_edges)

        assert len(data["nodes"]) == 100
        assert len(data["edges"]) == 50
