"""Tests for ClaudeProposer.propose() — all Anthropic API calls are mocked,
these must never hit the real API.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from apps.annotation.models import Edge
from apps.annotation.services import create_edge, create_graph, create_node
from apps.llm.claude_proposer import ClaudeProposer
from apps.llm.models import FewShotExample, ProposerConfig
from apps.llm.proposer import ProposedEdge, ProposedNode
from apps.projects.models import Document, Project

pytestmark = pytest.mark.django_db

_NODE_LAYERS = [
    {
        "id": "main",
        "label": "Entity",
        "collapsed_by_default": False,
        "slots": [
            {
                "name": "entity_term",
                "required": True,
                "multivalued": False,
                "widget": "text",
                "description": "The entity involved.",
            }
        ],
    }
]

_EDGE_LAYERS = [
    {
        "id": "main",
        "label": "Claim",
        "collapsed_by_default": False,
        "slots": [
            {
                "name": "claim_strength",
                "required": True,
                "multivalued": False,
                "widget": "select",
                "description": "Strength of the claim.",
                "choices": [{"value": "tendency", "description": "A tendency."}],
            }
        ],
    }
]


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user("claude-proposer-admin", password="x")


@pytest.fixture
def project(admin_user, latest_schema):
    p = Project.objects.create(
        name="Claude Proposer Test Project", created_by=admin_user
    )
    p.active_schema = latest_schema
    p.save(update_fields=["active_schema"])
    return p


@pytest.fixture
def document_row(project):
    return Document.objects.create(
        project=project, source=Document.SOURCE_RIS_IMPORT, title="Paper"
    )


@pytest.fixture
def graph(document_row, admin_user, latest_schema):
    return create_graph(document_row, admin_user, latest_schema)


def _fake_schema_view():
    def form_spec(class_name):
        if class_name == ClaudeProposer.NODE_CLASS:
            return _NODE_LAYERS
        if class_name == ClaudeProposer.EDGE_CLASS:
            return _EDGE_LAYERS
        raise ValueError(class_name)

    return SimpleNamespace(form_spec=form_spec)


def _fake_document(text: str, project: Project) -> SimpleNamespace:
    return SimpleNamespace(canonical_text=text, project=project)


def _config(**overrides):
    defaults = dict(
        model="claude-sonnet-5",
        max_tokens=1024,
        api_key_env_var="LOOM_TEST_ANTHROPIC_KEY",
        max_proposals_per_document=20,
    )
    defaults.update(overrides)
    return ProposerConfig(**defaults)


def _mock_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


def _make_complete_edge(graph, source_text: str, order: int = 0) -> Edge:
    subject = create_node(graph, {"name": f"Subject{order}"})
    obj = create_node(graph, {"name": f"Object{order}"})
    edge = create_edge(
        graph,
        subject,
        obj,
        {"predicate": "reduces", "original_sentence": source_text},
    )
    edge.status = Edge.STATUS_COMPLETE
    edge.save(update_fields=["status"])
    return edge


class TestClaudeProposerPropose:
    def test_propose_returns_correct_types(self, monkeypatch, project):
        monkeypatch.setenv("LOOM_TEST_ANTHROPIC_KEY", "sk-test")
        claims = [
            {
                "subject": {"name": "Wolf population", "entity_term": "wolves"},
                "object": {"name": "Deer population", "entity_term": "deer"},
                "edge": {"claim_strength": "tendency"},
                "source_text": "Wolves reduce deer populations.",
            },
            {
                "subject": {"name": "Soil nitrogen", "entity_term": "nitrogen"},
                "object": {"name": "Plant growth", "entity_term": "plants"},
                "edge": {"claim_strength": "tendency"},
                "source_text": "Nitrogen increases plant growth.",
            },
        ]
        response = _mock_response(json.dumps(claims))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        with patch(
            "apps.llm.claude_proposer.anthropic.Anthropic", return_value=mock_client
        ):
            proposer = ClaudeProposer(_config())
            nodes, edges = proposer.propose(
                _fake_document(
                    "Wolves reduce deer populations. Nitrogen increases plant growth.",
                    project,
                ),
                _fake_schema_view(),
            )

        assert len(edges) == 2
        assert all(isinstance(e, ProposedEdge) for e in edges)
        assert len(nodes) == 4
        assert all(isinstance(n, ProposedNode) for n in nodes)
        assert edges[0].subject_name == "Wolf population"
        assert edges[0].object_name == "Deer population"
        assert edges[0].source_span_start is not None

    def test_propose_api_error_returns_empty(self, monkeypatch, project):
        monkeypatch.setenv("LOOM_TEST_ANTHROPIC_KEY", "sk-test")
        mock_client = MagicMock()
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        mock_client.messages.create.side_effect = anthropic.APIError(
            "boom", request, body=None
        )

        with patch(
            "apps.llm.claude_proposer.anthropic.Anthropic", return_value=mock_client
        ):
            proposer = ClaudeProposer(_config())
            nodes, edges = proposer.propose(
                _fake_document("Some text.", project), _fake_schema_view()
            )

        assert nodes == []
        assert edges == []

    def test_propose_json_parse_error_returns_empty(self, monkeypatch, project):
        monkeypatch.setenv("LOOM_TEST_ANTHROPIC_KEY", "sk-test")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(
            "Sure, here are the claims: not actually JSON"
        )

        with patch(
            "apps.llm.claude_proposer.anthropic.Anthropic", return_value=mock_client
        ):
            proposer = ClaudeProposer(_config())
            nodes, edges = proposer.propose(
                _fake_document("Some text.", project), _fake_schema_view()
            )

        assert nodes == []
        assert edges == []

    def test_propose_truncates_long_text(self, monkeypatch, project):
        monkeypatch.setenv("LOOM_TEST_ANTHROPIC_KEY", "sk-test")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(json.dumps([]))
        long_text = "A" * 20000

        with patch(
            "apps.llm.claude_proposer.anthropic.Anthropic", return_value=mock_client
        ):
            proposer = ClaudeProposer(_config())
            proposer.propose(_fake_document(long_text, project), _fake_schema_view())

        _, kwargs = mock_client.messages.create.call_args
        sent_content = kwargs["messages"][-1]["content"]
        assert len(sent_content) <= 8100

    def test_propose_non_list_json_returns_empty(self, monkeypatch, project):
        monkeypatch.setenv("LOOM_TEST_ANTHROPIC_KEY", "sk-test")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(
            json.dumps({"not": "a list"})
        )

        with patch(
            "apps.llm.claude_proposer.anthropic.Anthropic", return_value=mock_client
        ):
            proposer = ClaudeProposer(_config())
            nodes, edges = proposer.propose(
                _fake_document("Some text.", project), _fake_schema_view()
            )

        assert nodes == []
        assert edges == []

    def test_propose_respects_max_proposals_per_document(self, monkeypatch, project):
        monkeypatch.setenv("LOOM_TEST_ANTHROPIC_KEY", "sk-test")
        claims = [
            {
                "subject": {"name": f"S{i}"},
                "object": {"name": f"O{i}"},
                "edge": {},
                "source_text": "",
            }
            for i in range(5)
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(json.dumps(claims))

        with patch(
            "apps.llm.claude_proposer.anthropic.Anthropic", return_value=mock_client
        ):
            proposer = ClaudeProposer(_config(max_proposals_per_document=2))
            nodes, edges = proposer.propose(
                _fake_document("Some text.", project), _fake_schema_view()
            )

        assert len(edges) == 2
        assert len(nodes) == 4


class TestClaudeProposerFewShot:
    def test_few_shot_included_in_messages(self, monkeypatch, project, graph):
        monkeypatch.setenv("LOOM_TEST_ANTHROPIC_KEY", "sk-test")
        for i in range(3):
            edge = _make_complete_edge(graph, f"Sentence {i}.", order=i)
            FewShotExample.objects.create(project=project, edge=edge, display_order=i)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(json.dumps([]))

        with patch(
            "apps.llm.claude_proposer.anthropic.Anthropic", return_value=mock_client
        ):
            proposer = ClaudeProposer(_config())
            proposer.propose(_fake_document("Some text.", project), _fake_schema_view())

        _, kwargs = mock_client.messages.create.call_args
        assert len(kwargs["messages"]) == 3 * 2 + 1

    def test_few_shot_capped(self, monkeypatch, project, graph):
        monkeypatch.setenv("LOOM_TEST_ANTHROPIC_KEY", "sk-test")
        for i in range(10):
            edge = _make_complete_edge(graph, f"Sentence {i}.", order=i)
            FewShotExample.objects.create(project=project, edge=edge, display_order=i)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(json.dumps([]))

        with patch(
            "apps.llm.claude_proposer.anthropic.Anthropic", return_value=mock_client
        ):
            proposer = ClaudeProposer(_config(max_shots=3))
            proposer.propose(_fake_document("Some text.", project), _fake_schema_view())

        _, kwargs = mock_client.messages.create.call_args
        assert len(kwargs["messages"]) == 3 * 2 + 1

    def test_zero_shot_when_no_examples(self, monkeypatch, project):
        monkeypatch.setenv("LOOM_TEST_ANTHROPIC_KEY", "sk-test")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(json.dumps([]))

        with patch(
            "apps.llm.claude_proposer.anthropic.Anthropic", return_value=mock_client
        ):
            proposer = ClaudeProposer(_config())
            proposer.propose(_fake_document("Some text.", project), _fake_schema_view())

        _, kwargs = mock_client.messages.create.call_args
        assert len(kwargs["messages"]) == 1
