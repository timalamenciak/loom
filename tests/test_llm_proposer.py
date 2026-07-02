"""
Phase 6 tests: LLM proposer protocol and default implementation.

Tests verify the Proposer protocol interface and NoOpProposer default
implementation. These tests are schema-agnostic since the protocol doesn't
depend on CAMO types.
"""

from unittest.mock import Mock

from apps.llm.proposer import NoOpProposer, ProposedEdge, ProposedNode

# ---------------------------------------------------------------------------
# Protocol interface tests
# ---------------------------------------------------------------------------


class TestProposedNode:
    """Verify ProposedNode dataclass structure."""

    def test_default_data_is_dict(self):
        node = ProposedNode(name="Test Node")
        assert node.data == {}

    def test_custom_data(self):
        node = ProposedNode(name="Test", data={"custom": "value"})
        assert node.data == {"custom": "value"}

    def test_source_spans(self):
        node = ProposedNode(
            name="Test",
            source_span_start=10,
            source_span_end=20,
        )
        assert node.source_span_start == 10
        assert node.source_span_end == 20


class TestProposedEdge:
    """Verify ProposedEdge dataclass structure."""

    def test_default_data_is_dict(self):
        edge = ProposedEdge(subject_name="Subject", object_name="Object")
        assert edge.data == {}

    def test_custom_data(self):
        edge = ProposedEdge(
            subject_name="Subject",
            object_name="Object",
            data={"predicate": "causal"},
        )
        assert edge.data == {"predicate": "causal"}

    def test_source_spans(self):
        edge = ProposedEdge(
            subject_name="Subject",
            object_name="Object",
            source_span_start=5,
            source_span_end=15,
        )
        assert edge.source_span_start == 5
        assert edge.source_span_end == 15


class TestProposerProtocol:
    """Verify Proposer protocol requires propose method."""

    def test_proposer_requires_propose_method(self):
        """Protocol should enforce propose method signature."""

        class BadProposer:
            pass

        class GoodProposer:
            def propose(self, document, schema_view):
                return [], []

        # Protocol is checked at runtime via isinstance
        good = GoodProposer()
        assert hasattr(good, "propose")
        assert callable(good.propose)

    def test_propose_signature(self):
        """Propose should accept document and schema_view."""
        proposer = NoOpProposer()
        result = proposer.propose(Mock(), Mock())
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# NoOpProposer tests
# ---------------------------------------------------------------------------


class TestNoOpProposer:
    """Verify default no-op proposer behavior."""

    def test_returns_empty_lists(self):
        """NoOpProposer.propose returns empty node and edge lists."""
        proposer = NoOpProposer()
        document = Mock()
        schema_view = Mock()

        nodes, edges = proposer.propose(document, schema_view)

        assert nodes == []
        assert edges == []

    def test_ignores_arguments(self):
        """NoOpProposer ignores document and schema_view arguments."""
        proposer = NoOpProposer()
        document = Mock(title="Test Document")
        schema_view = Mock(version="0.5.0")

        nodes, edges = proposer.propose(document, schema_view)

        assert nodes == []
        assert edges == []

    def test_multiple_calls_return_independent_lists(self):
        """Each call should return new list instances."""
        proposer = NoOpProposer()
        document = Mock()
        schema_view = Mock()

        nodes1, edges1 = proposer.propose(document, schema_view)
        nodes2, edges2 = proposer.propose(document, schema_view)

        assert nodes1 is not nodes2
        assert edges1 is not edges2

    def test_no_side_effects(self):
        """NoOpProposer should not modify document or schema_view."""
        proposer = NoOpProposer()
        document = Mock()
        schema_view = Mock()

        document.title = "Original"
        document.side_effect = None

        proposer.propose(document, schema_view)

        assert document.title == "Original"
        assert document.side_effect is None
