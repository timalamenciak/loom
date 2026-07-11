"""Tests for apps.llm.triggers.propose_for_document — the ProposerConfig ->
draft node/edge glue. ClaudeProposer.propose is always mocked; these must
never hit the real Anthropic API.
"""

from unittest.mock import patch

import pytest

from apps.annotation.models import CausalGraph, Edge, Node
from apps.llm.models import ProposerConfig
from apps.llm.proposer import ProposedEdge, ProposedNode
from apps.projects.models import Assignment, Document, Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        "llm-trigger-admin", "llm-trigger-admin@test.example", "password"
    )


@pytest.fixture
def project(admin_user, latest_schema):
    p = Project.objects.create(name="LLM Trigger Test Project", created_by=admin_user)
    p.active_schema = latest_schema
    p.save(update_fields=["active_schema"])
    return p


@pytest.fixture
def annotator(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user("llm-trigger-annotator", password="x")


@pytest.fixture
def document(project):
    return Document.objects.create(
        project=project,
        source=Document.SOURCE_RIS_IMPORT,
        title="Paper",
        canonical_text="Wolves reduce deer populations.",
    )


@pytest.fixture
def assignment(project, document, annotator, admin_user):
    return Assignment.objects.create(
        project=project,
        document=document,
        annotator=annotator,
        assigned_by=admin_user,
        status=Assignment.STATUS_ASSIGNED,
    )


def _proposed_pair(i: int) -> tuple[ProposedNode, ProposedNode, ProposedEdge]:
    subject = ProposedNode(name=f"Subject{i}", data={"name": f"Subject{i}"})
    obj = ProposedNode(name=f"Object{i}", data={"name": f"Object{i}"})
    edge = ProposedEdge(
        subject_name=subject.name,
        object_name=obj.name,
        data={"predicate": "reduces"},
    )
    return subject, obj, edge


def _make_config(project, **overrides) -> ProposerConfig:
    defaults = dict(
        project=project,
        is_enabled=True,
        trigger=ProposerConfig.TRIGGER_ON_ASSIGNMENT,
        api_key_env_var="LOOM_TEST_TRIGGER_KEY",
        max_proposals_per_document=20,
    )
    defaults.update(overrides)
    return ProposerConfig.objects.create(**defaults)


class TestProposeForDocument:
    def test_trigger_creates_draft_edges(self, project, document, assignment):
        _make_config(project)
        pairs = [_proposed_pair(i) for i in range(2)]
        nodes = [n for pair in pairs for n in pair[:2]]
        edges = [pair[2] for pair in pairs]

        with patch(
            "apps.llm.claude_proposer.ClaudeProposer.propose",
            return_value=(nodes, edges),
        ):
            from apps.llm.triggers import propose_for_document

            propose_for_document(document, project)

        graph = CausalGraph.objects.get(
            document=document, annotator=assignment.annotator
        )
        created_edges = Edge.objects.filter(graph=graph)
        assert created_edges.count() == 2
        assert all(e.status == Edge.STATUS_DRAFT for e in created_edges)
        assert all(e.origin == Edge.ORIGIN_LLM_PROPOSED for e in created_edges)
        assert (
            Node.objects.filter(graph=graph, origin=Node.ORIGIN_LLM_PROPOSED).count()
            == 4
        )

    def test_trigger_skipped_when_disabled(self, project, document, assignment):
        _make_config(project, is_enabled=False)

        with patch("apps.llm.claude_proposer.ClaudeProposer.propose") as mock_propose:
            from apps.llm.triggers import propose_for_document

            propose_for_document(document, project)

        mock_propose.assert_not_called()
        assert not CausalGraph.objects.filter(document=document).exists()
        assert not Edge.objects.exists()

    def test_trigger_caps_at_max(self, project, document, assignment):
        _make_config(project, max_proposals_per_document=20)
        pairs = [_proposed_pair(i) for i in range(30)]
        nodes = [n for pair in pairs for n in pair[:2]]
        edges = [pair[2] for pair in pairs]

        with patch(
            "apps.llm.claude_proposer.ClaudeProposer.propose",
            return_value=(nodes, edges),
        ):
            from apps.llm.triggers import propose_for_document

            propose_for_document(document, project)

        graph = CausalGraph.objects.get(
            document=document, annotator=assignment.annotator
        )
        assert Edge.objects.filter(graph=graph).count() == 20
