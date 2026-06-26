"""
LLM proposal seam — disabled by default (LLM_PROPOSALS_ENABLED = False).

When enabled in a future phase, a concrete Proposer subclass replaces
NoOpProposer.  The seam guarantees:
  - Proposals land as origin='llm_proposed', status='draft'.
  - No proposal auto-promotes to 'complete' or 'gold'.
  - All UI gating checks LLM_PROPOSALS_ENABLED before rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ProposedNode:
    name: str
    data: dict = field(default_factory=dict)
    source_span_start: int | None = None
    source_span_end: int | None = None


@dataclass
class ProposedEdge:
    subject_name: str
    object_name: str
    data: dict = field(default_factory=dict)
    source_span_start: int | None = None
    source_span_end: int | None = None


class Proposer(Protocol):
    """Interface for LLM-backed proposers."""

    def propose(
        self,
        document,
        schema_view,
    ) -> tuple[list[ProposedNode], list[ProposedEdge]]:
        """Return proposed nodes and edges for *document* under *schema_view*."""
        ...


class NoOpProposer:
    """Default no-op proposer; ships as the only implementation."""

    def propose(self, document, schema_view):
        return [], []
