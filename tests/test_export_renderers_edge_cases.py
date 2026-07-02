"""
Phase 6 tests: Export renderers edge cases.

Verify the renderers handle edge cases like missing templates, invalid
percentages, and unknown values. Tests are pure Python - no database required.
"""

import pytest

from apps.export.renderers import (
    FCMWeight,
    RosettaStatement,
    render_fcm,
    render_rosetta,
)

# ---------------------------------------------------------------------------
# Fixtures
# ------ ------ -----


@pytest.fixture
def minimal_schema_yaml():
    """Minimal schema with PredicateEnum."""
    return """
id: https://example.org/camo
name: camo
imports: [linkml:types]

enums:
  PredicateEnum:
    permissible_values:
      causal:
        annotations:
          rosetta_template: "{subject} causes {object}"
          fcm_sign: "+"
      correlation:
        annotations:
          rosetta_template: "{subject} correlates with {object}"
          fcm_sign: "?"
      inverse:
        annotations:
          rosetta_template: "{object} causes {subject}"
          fcm_sign: "-"
"""  # noqa: E501


@pytest.fixture
def graph_data_with_edges():
    """Sample graph data with edges."""
    return {
        "nodes": [
            {"node_id": "n1", "name": "Node A"},
            {"node_id": "n2", "name": "Node B"},
        ],
        "edges": [
            {
                "edge_id": "e1",
                "subject": "n1",
                "object": "n2",
                "predicate": "causal",
                "claim_strength": "strong_tendency",
            },
            {
                "edge_id": "e2",
                "subject": "n2",
                "object": "n1",
                "predicate": "correlation",
                "claim_strength": "weak_tendency",
            },
        ],
    }


# ---------------------------------------------------------------------------
# render_rosetta tests
# --------------------------------------------------------------------------


class TestRenderRosetta:
    """Verify render_rosetta function behavior."""

    def test_basic_rendering(self, minimal_schema_yaml, graph_data_with_edges):
        """Renders rosetta statements for edges with templates."""
        result = render_rosetta(graph_data_with_edges, minimal_schema_yaml)

        assert len(result) == 2
        assert isinstance(result[0], RosettaStatement)
        assert "causes" in result[0].statement

    def test_replaces_placeholders(self, minimal_schema_yaml, graph_data_with_edges):
        """Replaces {subject} and {object} placeholders."""
        result = render_rosetta(graph_data_with_edges, minimal_schema_yaml)

        assert "Node A" in result[0].statement
        assert "Node B" in result[0].statement

    def test_missing_template_ignored(self, minimal_schema_yaml, graph_data_with_edges):
        """Edges without templates are skipped."""
        data = {
            "nodes": [
                {"node_id": "n1", "name": "Node A"},
                {"node_id": "n2", "name": "Node B"},
            ],
            "edges": [
                {
                    "edge_id": "e1",
                    "subject": "n1",
                    "object": "n2",
                    "predicate": "unknown_predicate",  # No template
                },
            ],
        }

        result = render_rosetta(data, minimal_schema_yaml)

        assert len(result) == 0

    def test_missing_nodes_shows_id(self, minimal_schema_yaml):
        """Missing nodes show their IDs instead of names."""
        data = {
            "nodes": [],
            "edges": [
                {
                    "edge_id": "e1",
                    "subject": "n1",
                    "object": "n2",
                    "predicate": "causal",
                },
            ],
        }

        result = render_rosetta(data, minimal_schema_yaml)

        assert "n1" in result[0].statement
        assert "n2" in result[0].statement

    def test_certainty_grade_modifies_statement(self, minimal_schema_yaml):
        """Low certainty adds 'Possibly:' prefix."""
        data = {
            "nodes": [
                {"node_id": "n1", "name": "Node A"},
                {"node_id": "n2", "name": "Node B"},
            ],
            "edges": [
                {
                    "edge_id": "e1",
                    "subject": "n1",
                    "object": "n2",
                    "predicate": "causal",
                    "certainty_grade": 0.3,  # Below 0.5
                },
            ],
        }

        result = render_rosetta(data, minimal_schema_yaml)

        assert result[0].statement.startswith("Possibly")
        assert "causes" in result[0].statement

    def test_certainty_graph_high_unchanged(self, minimal_schema_yaml):
        """High certainty doesn't modify statement."""
        data = {
            "nodes": [
                {"node_id": "n1", "name": "Node A"},
                {"node_id": "n2", "name": "Node B"},
            ],
            "edges": [
                {
                    "edge_id": "e1",
                    "subject": "n1",
                    "object": "n2",
                    "predicate": "causal",
                    "certainty_grade": 0.8,  # Above 0.5
                },
            ],
        }

        result = render_rosetta(data, minimal_schema_yaml)

        assert not result[0].statement.startswith("Possibly")

    def test_invalid_certainty_ignored(self, minimal_schema_yaml):
        """Invalid certainty values don't crash."""
        data = {
            "nodes": [
                {"node_id": "n1", "name": "Node A"},
                {"node_id": "n2", "name": "Node B"},
            ],
            "edges": [
                {
                    "edge_id": "e1",
                    "subject": "n1",
                    "object": "n2",
                    "predicate": "causal",
                    "certainty_grade": "invalid",  # Not a number
                },
            ],
        }

        result = render_rosetta(data, minimal_schema_yaml)

        assert len(result) == 1
        assert not result[0].statement.startswith("Possibly")

    def test_missing_certainty_unchanged(self, minimal_schema_yaml):
        """Missing certainty doesn't modify statement."""
        data = {
            "nodes": [
                {"node_id": "n1", "name": "Node A"},
                {"node_id": "n2", "name": "Node B"},
            ],
            "edges": [
                {
                    "edge_id": "e1",
                    "subject": "n1",
                    "object": "n2",
                    "predicate": "causal",
                    # No certainty_grade
                },
            ],
        }

        result = render_rosetta(data, minimal_schema_yaml)

        assert not result[0].statement.startswith("Possibly")


# ---------------------------------------------------------------------------
# render_fcm tests
# --------------------------------------------------------------------------


class TestRenderFCM:
    """Verify render_fcm function behavior."""

    def test_basic_rendering(self, minimal_schema_yaml, graph_data_with_edges):
        """Renders FCM weights for edges with predicates."""
        result = render_fcm(graph_data_with_edges, minimal_schema_yaml)

        assert len(result) == 2
        assert isinstance(result[0], FCMWeight)

    def test_sign_mapping(self, minimal_schema_yaml, graph_data_with_edges):
        """Maps fcm_sign to integer."""
        result = render_fcm(graph_data_with_edges, minimal_schema_yaml)

        assert result[0].sign == 1  # causal has +
        assert result[1].sign == 0  # correlation has ?

    def test_strength_weights(self, minimal_schema_yaml, graph_data_with_edges):
        """Applies claim strength weights."""
        result = render_fcm(graph_data_with_edges, minimal_schema_yaml)

        # strong_tendency should have weight 0.8
        assert result[0].strength == 0.8
        # weak_tendency should have weight 0.3
        assert result[1].strength == 0.3

    def test_rounded_weight(self, minimal_schema_yaml, graph_data_with_edges):
        """Weight is rounded to 4 decimal places."""
        result = render_fcm(graph_data_with_edges, minimal_schema_yaml)

        # sign * strength = 1 * 0.8 = 0.8
        assert result[0].weight == 0.8

    def test_unknown_predicate_gets_default_sign(self, minimal_schema_yaml):
        """Unknown predicates get sign 0."""
        data = {
            "nodes": [],
            "edges": [
                {
                    "edge_id": "e1",
                    "subject": "n1",
                    "object": "n2",
                    "predicate": "unknown_predicate",  # No fcm_sign
                },
            ],
        }

        result = render_fcm(data, minimal_schema_yaml)

        assert result[0].sign == 0

    def test_default_strength(self, minimal_schema_yaml):
        """Unknown claim strength uses default (0.5)."""
        data = {
            "nodes": [],
            "edges": [
                {
                    "edge_id": "e1",
                    "subject": "n1",
                    "object": "n2",
                    "predicate": "causal",
                    "claim_strength": "unknown_strength",  # Not in map
                },
            ],
        }

        result = render_fcm(data, minimal_schema_yaml)

        assert result[0].strength == 0.5

    def test_missing_predicate_skipped(self, minimal_schema_yaml):
        """Edges without predicate are skipped."""
        data = {
            "nodes": [],
            "edges": [
                {
                    "edge_id": "e1",
                    "subject": "n1",
                    "object": "n2",
                    # No predicate
                },
            ],
        }

        result = render_fcm(data, minimal_schema_yaml)

        assert len(result) == 0

    def test_negative_sign(self, minimal_schema_yaml):
        """Negative fcm_sign maps to -1."""
        data = {
            "nodes": [],
            "edges": [
                {
                    "edge_id": "e1",
                    "subject": "n1",
                    "object": "n2",
                    "predicate": "inverse",  # Has fcm_sign: "-"
                },
            ],
        }

        result = render_fcm(data, minimal_schema_yaml)

        assert result[0].sign == -1

    def test_calculates_weight_correctly(self, minimal_schema_yaml):
        """Weight = sign * strength, correctly calculated."""
        data = {
            "nodes": [],
            "edges": [
                {
                    "edge_id": "e1",
                    "subject": "n1",
                    "object": "n2",
                    "predicate": "inverse",
                    "claim_strength": "strong_tendency",
                },
            ],
        }

        result = render_fcm(data, minimal_schema_yaml)

        # sign = -1, strength = 0.8, weight = -0.8
        assert result[0].sign == -1
        assert result[0].strength == 0.8
        assert result[0].weight == -0.8
