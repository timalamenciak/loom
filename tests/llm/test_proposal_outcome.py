"""Tests for ProposalOutcome tracking — apps/llm/views.py's accept/reject
actions record acceptance-rate and edit-distance metrics.
"""

import pytest
from django.urls import reverse

from apps.annotation.models import Edge, Node
from apps.annotation.services import create_edge, create_graph, create_node
from apps.llm.models import ProposalOutcome
from apps.projects.models import Document, Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        "proposal-outcome-admin", "proposal-outcome-admin@test.example", "password"
    )


@pytest.fixture
def project(admin_user, latest_schema):
    p = Project.objects.create(
        name="Proposal Outcome Test Project", created_by=admin_user
    )
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


def _make_proposed_edge(graph, data=None):
    data = data or {"predicate": "reduces", "claim_strength": "tendency"}
    subject = create_node(graph, {"name": "Wolves"}, origin=Node.ORIGIN_LLM_PROPOSED)
    obj = create_node(graph, {"name": "Deer"}, origin=Node.ORIGIN_LLM_PROPOSED)
    return create_edge(graph, subject, obj, dict(data), origin=Edge.ORIGIN_LLM_PROPOSED)


class TestAcceptRecordsOutcome:
    def test_accept_records_outcome(self, client, project, graph, admin_user):
        edge = _make_proposed_edge(graph)
        client.force_login(admin_user)

        client.post(reverse("proposal-accept", args=[edge.pk]))

        outcome = ProposalOutcome.objects.get(edge=edge)
        assert outcome.accepted_at is not None
        assert outcome.rejected_at is None
        assert outcome.time_to_review_seconds is not None
        assert outcome.time_to_review_seconds >= 0
        edge.refresh_from_db()
        assert edge.status == Edge.STATUS_COMPLETE

    def test_accept_records_edit_distance_zero(
        self, client, project, graph, admin_user
    ):
        data = {"predicate": "reduces", "claim_strength": "tendency"}
        edge = _make_proposed_edge(graph, data)
        client.force_login(admin_user)

        client.post(reverse("proposal-accept", args=[edge.pk]))

        outcome = ProposalOutcome.objects.get(edge=edge)
        assert outcome.edit_distance == 0

    def test_accept_records_edit_distance_nonzero(
        self, client, project, graph, admin_user
    ):
        original = {
            "predicate": "reduces",
            "claim_strength": "tendency",
            "note": "a",
            "constant": "x",
        }
        edge = _make_proposed_edge(graph, original)
        # Snapshot the *stored* data (create_edge may enrich it, e.g. tag an
        # annotator) as the proposal baseline, then simulate a human edit
        # before accept — matching the real "Edit before accepting" flow,
        # which saves the edge in a separate request before Accept is clicked.
        ProposalOutcome.objects.create(edge=edge, proposed_data=dict(edge.data))
        edited = dict(edge.data)
        edited["predicate"] = "increases"
        edited["claim_strength"] = "strong"
        edited["note"] = "b"
        edge.data = edited
        edge.save(update_fields=["data"])
        client.force_login(admin_user)

        client.post(reverse("proposal-accept", args=[edge.pk]))

        outcome = ProposalOutcome.objects.get(edge=edge)
        assert outcome.edit_distance == 3


class TestRejectRecordsOutcome:
    def test_reject_records_rejection(self, client, project, graph, admin_user):
        edge = _make_proposed_edge(graph)
        edge_pk = edge.pk
        client.force_login(admin_user)

        client.post(reverse("proposal-reject", args=[edge_pk]))

        assert not Edge.objects.filter(pk=edge_pk).exists()
        outcome = ProposalOutcome.objects.get(rejected_at__isnull=False)
        assert outcome.rejected_at is not None
        assert outcome.accepted_at is None
        assert outcome.time_to_review_seconds is not None
        assert outcome.time_to_review_seconds >= 0
        # SET_NULL, not CASCADE — the metrics row survives the edge's deletion.
        assert outcome.edge_id is None
