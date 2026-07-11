"""Tests for ClaudeProposer.propose() — all Anthropic API calls are mocked,
these must never hit the real API.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx

from apps.llm.claude_proposer import ClaudeProposer
from apps.llm.models import ProposerConfig
from apps.llm.proposer import ProposedEdge, ProposedNode

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


def _fake_schema_view():
    def form_spec(class_name):
        if class_name == ClaudeProposer.NODE_CLASS:
            return _NODE_LAYERS
        if class_name == ClaudeProposer.EDGE_CLASS:
            return _EDGE_LAYERS
        raise ValueError(class_name)

    return SimpleNamespace(form_spec=form_spec)


def _fake_document(text: str):
    return SimpleNamespace(canonical_text=text)


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


class TestClaudeProposerPropose:
    def test_propose_returns_correct_types(self, monkeypatch):
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
                    "Wolves reduce deer populations. Nitrogen increases plant growth."
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

    def test_propose_api_error_returns_empty(self, monkeypatch):
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
                _fake_document("Some text."), _fake_schema_view()
            )

        assert nodes == []
        assert edges == []

    def test_propose_json_parse_error_returns_empty(self, monkeypatch):
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
                _fake_document("Some text."), _fake_schema_view()
            )

        assert nodes == []
        assert edges == []

    def test_propose_truncates_long_text(self, monkeypatch):
        monkeypatch.setenv("LOOM_TEST_ANTHROPIC_KEY", "sk-test")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(json.dumps([]))
        long_text = "A" * 20000

        with patch(
            "apps.llm.claude_proposer.anthropic.Anthropic", return_value=mock_client
        ):
            proposer = ClaudeProposer(_config())
            proposer.propose(_fake_document(long_text), _fake_schema_view())

        _, kwargs = mock_client.messages.create.call_args
        sent_content = kwargs["messages"][0]["content"]
        assert len(sent_content) <= 8100

    def test_propose_non_list_json_returns_empty(self, monkeypatch):
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
                _fake_document("Some text."), _fake_schema_view()
            )

        assert nodes == []
        assert edges == []

    def test_propose_respects_max_proposals_per_document(self, monkeypatch):
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
                _fake_document("Some text."), _fake_schema_view()
            )

        assert len(edges) == 2
        assert len(nodes) == 4
