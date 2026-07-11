"""Proposal trigger — turns a project's ProposerConfig into draft proposals.

Wired into the assignment flow (apps/projects/services.py:assign_document)
for projects configured with trigger='on_assignment'. Per the LLM seam
guarantees in apps/llm/proposer.py, this only ever creates
status='draft', origin='llm_proposed' rows through the normal annotation
service layer for a human to accept or reject — nothing here promotes a
proposal to 'complete' or 'gold'.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def propose_for_document(document, project) -> None:
    from apps.annotation.views import get_schema_version
    from apps.llm.claude_proposer import ClaudeProposer
    from apps.llm.models import ProposerConfig
    from apps.projects.models import Assignment
    from apps.schemas.schema_engine import LoomSchemaView

    config = ProposerConfig.objects.filter(project=project, is_enabled=True).first()
    if config is None:
        return

    assignment = (
        Assignment.objects.filter(document=document, project=project)
        .order_by("-assigned_at")
        .first()
    )
    if assignment is None:
        return

    schema_version = get_schema_version(project)
    if schema_version is None:
        return

    graph = _get_or_create_graph(document, assignment, schema_version, project)
    schema_view = LoomSchemaView(schema_version, project=project)

    try:
        nodes, edges = ClaudeProposer(config).propose(document, schema_view)
    except Exception:
        logger.exception(
            "LLM proposal trigger failed for document=%s project=%s",
            document.pk,
            project.pk,
        )
        return

    _materialize_proposals(
        graph, document, project, nodes, edges, config.max_proposals_per_document
    )


def _get_or_create_graph(document, assignment, schema_version, project):
    from apps.annotation.models import CausalGraph
    from apps.annotation.services import create_graph

    if assignment.graph_id:
        return assignment.graph

    graph = (
        CausalGraph.objects.filter(document=document, annotator=assignment.annotator)
        .order_by("-updated_at", "-created_at", "-pk")
        .first()
    )
    if graph:
        return graph

    return create_graph(
        document,
        assignment.annotator,
        schema_version,
        ontology_snapshot=project.ontology_snapshot,
    )


def _materialize_proposals(
    graph, document, project, proposed_nodes, proposed_edges, limit
) -> None:
    from apps.annotation import services as annotation_services
    from apps.annotation.models import Edge, Node
    from apps.llm.models import ProposalOutcome

    capped_edges = proposed_edges[:limit]
    needed_names = {edge.subject_name for edge in capped_edges} | {
        edge.object_name for edge in capped_edges
    }

    node_by_name = {}
    for proposed in proposed_nodes:
        if proposed.name not in needed_names or proposed.name in node_by_name:
            continue
        node_by_name[proposed.name] = annotation_services.create_node(
            graph,
            dict(proposed.data, name=proposed.name),
            origin=Node.ORIGIN_LLM_PROPOSED,
        )

    for proposed in capped_edges:
        subject = node_by_name.get(proposed.subject_name)
        object_node = node_by_name.get(proposed.object_name)
        if subject is None or object_node is None:
            continue
        edge = annotation_services.create_edge(
            graph,
            subject,
            object_node,
            proposed.data,
            origin=Edge.ORIGIN_LLM_PROPOSED,
        )
        ProposalOutcome.objects.create(
            project=project,
            document=document,
            edge=edge,
            proposed_data=dict(edge.data),
        )
