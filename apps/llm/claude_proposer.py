"""ClaudeProposer — the concrete Proposer implementation for the LLM seam.

Disabled by default (LLM_PROPOSALS_ENABLED = False, and per-project via
ProposerConfig.is_enabled) and only ever produces draft proposals for a human
to accept or reject — see apps/llm/proposer.py's module docstring for the
guarantees this seam makes. Nothing here writes to the annotation graph;
callers are responsible for turning ProposedNode/ProposedEdge into draft
Node/Edge rows through the normal annotation service layer.

CausalNode/CausalEdge are the two class names hardcoded below — that's not a
violation of "derive everything from the schema" (see CLAUDE.md's "one
defining constraint"): CAMO's own REQUIRED_CAMO_CLASSES
(apps/schemas/services.py) guarantees every valid schema defines exactly
these two class names, the same way SourceDocument is a deliberate,
documented schema-agnosticism exception. Every *slot* under those two
classes is still derived entirely from schema_view.form_spec() via
build_system_prompt() — nothing about CAMO's fields is hardcoded.
"""

from __future__ import annotations

import json
import logging
import os

import anthropic

from .models import ProposerConfig
from .prompt_builder import build_system_prompt
from .proposer import ProposedEdge, ProposedNode

logger = logging.getLogger(__name__)

_MAX_DOCUMENT_CHARS = 8000
_TRUNCATION_NOTICE = "\n\n[... document text truncated for length ...]"


class ClaudeProposer:
    """Calls the Claude API to draft node/edge proposals for one document."""

    NODE_CLASS = "CausalNode"
    EDGE_CLASS = "CausalEdge"

    def __init__(self, config: ProposerConfig):
        self.config = config

    def propose(
        self, document, schema_view
    ) -> tuple[list[ProposedNode], list[ProposedEdge]]:
        """*schema_view* must be project-bound (constructed via
        get_schema_view(schema_version, project=document.project)) — that's
        what makes form_spec() resolve globally_hidden_slots from the
        project's SchemaUIConfig. An unbound view (project=None) skips that
        resolution entirely, and a slot an admin hid from annotators would
        end up described to Claude in the prompt anyway.
        """
        system_prompt = build_system_prompt(
            {
                self.NODE_CLASS: schema_view.form_spec(self.NODE_CLASS),
                self.EDGE_CLASS: schema_view.form_spec(self.EDGE_CLASS),
            }
        )

        full_text = document.canonical_text or ""
        doc_text = full_text
        if len(doc_text) > _MAX_DOCUMENT_CHARS:
            doc_text = doc_text[:_MAX_DOCUMENT_CHARS] + _TRUNCATION_NOTICE

        client = anthropic.Anthropic(
            api_key=os.environ.get(self.config.api_key_env_var, "")
        )

        try:
            response = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": f"Extract causal claims from:\n\n{doc_text}",
                    }
                ],
            )
        except anthropic.APIError as exc:
            logger.warning("ClaudeProposer: API call failed: %s", exc)
            return [], []

        raw_text = response.content[0].text if response.content else ""
        try:
            claims = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.warning("ClaudeProposer: could not parse response as JSON: %s", exc)
            return [], []

        if not isinstance(claims, list):
            logger.warning(
                "ClaudeProposer: expected a JSON array, got %s", type(claims).__name__
            )
            return [], []

        nodes: list[ProposedNode] = []
        edges: list[ProposedEdge] = []
        limit = self.config.max_proposals_per_document

        for claim in claims[:limit]:
            if not isinstance(claim, dict):
                continue

            subject_data = claim.get("subject") or {}
            object_data = claim.get("object") or {}
            edge_data = claim.get("edge") or {}
            source_text = claim.get("source_text") or ""

            subject_name = subject_data.get("name", "")
            object_name = object_data.get("name", "")

            span_start, span_end = _find_span(full_text, source_text)

            nodes.append(
                ProposedNode(
                    name=subject_name,
                    data=subject_data,
                    source_span_start=span_start,
                    source_span_end=span_end,
                )
            )
            nodes.append(
                ProposedNode(
                    name=object_name,
                    data=object_data,
                    source_span_start=span_start,
                    source_span_end=span_end,
                )
            )
            edges.append(
                ProposedEdge(
                    subject_name=subject_name,
                    object_name=object_name,
                    data=edge_data,
                    source_span_start=span_start,
                    source_span_end=span_end,
                )
            )

        return nodes, edges


def _find_span(full_text: str, source_text: str) -> tuple[int | None, int | None]:
    """Locate *source_text* as a literal substring of *full_text*.

    Best-effort: an LLM-quoted sentence that doesn't match exactly (paraphrase,
    whitespace normalization) just yields no span rather than a wrong one — an
    annotator reviewing the draft proposal can fix it, per "spans are
    first-class" but nothing here fabricates an offset it isn't sure of.
    """
    if not source_text:
        return None, None
    start = full_text.find(source_text)
    if start == -1:
        return None, None
    return start, start + len(source_text)
