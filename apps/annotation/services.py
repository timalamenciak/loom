"""Service layer for annotation writes. All ORM mutations go through here."""

from contextlib import nullcontext

from django.db import transaction
from django.db.models import Q

from .models import CausalGraph, Edge, Node, WorkSession

# ── Graph ─────────────────────────────────────────────────────────────────────


@transaction.atomic
def create_graph(
    document, annotator, schema_version, ontology_snapshot=None
) -> CausalGraph:
    graph = CausalGraph.objects.create(
        document=document,
        annotator=annotator,
        schema_version=schema_version,
        ontology_snapshot=ontology_snapshot,
    )
    emit_audit(annotator, "graph.create", "CausalGraph", graph.pk)
    return graph


# ── Nodes ─────────────────────────────────────────────────────────────────────


@transaction.atomic
def create_node(
    graph: CausalGraph,
    data: dict,
    origin: str = Node.ORIGIN_HUMAN,
    actor=None,
) -> Node:
    name = data.get("name", "").strip() or _derive_name(data)
    category = data.get("entity_type", "")
    node = Node.objects.create(
        graph=graph,
        name=name,
        category=category,
        data=data,
        origin=origin,
        schema_version=graph.schema_version,
    )
    emit_audit(actor or graph.annotator, "node.create", "Node", node.pk, data)
    return node


@transaction.atomic
def update_node(node: Node, data: dict, actor=None) -> Node:
    node.name = data.get("name", "").strip() or _derive_name(data)
    node.category = data.get("entity_type", node.category)
    node.data = data
    node.save(update_fields=["name", "category", "data"])
    emit_audit(actor or node.graph.annotator, "node.update", "Node", node.pk, data)
    return node


@transaction.atomic
def set_node_source_spans(node: Node, spans, actor) -> None:
    """Replace the excerpts grounding *node* without stealing another node's spans."""
    requested = {span.pk: span for span in spans}
    current = list(node.spans.all())

    for span in current:
        if span.pk not in requested:
            span.node = None
            span.save(update_fields=["node"])
            emit_audit(
                actor,
                "span.unlink",
                "TextSpan",
                span.pk,
                {"node_id": node.pk},
            )

    for span in requested.values():
        if span.node_id not in {None, node.pk}:
            continue
        if span.node_id != node.pk:
            span.node = node
            span.save(update_fields=["node"])
            emit_audit(
                actor,
                "span.link",
                "TextSpan",
                span.pk,
                {"node_id": node.pk},
            )


# ── Edges ─────────────────────────────────────────────────────────────────────


@transaction.atomic
def create_edge(
    graph: CausalGraph,
    subject: Node,
    object_node: Node,
    data: dict,
    origin: str = Edge.ORIGIN_HUMAN,
    actor=None,
) -> Edge:
    if subject.graph_id != graph.pk or object_node.graph_id != graph.pk:
        raise ValueError("Edge endpoints must belong to the edge graph.")
    edge = Edge.objects.create(
        graph=graph,
        subject=subject,
        object=object_node,
        predicate=data.get("predicate", ""),
        claim_strength=data.get("claim_strength", ""),
        data=data,
        origin=origin,
        schema_version=graph.schema_version,
    )
    emit_audit(actor or graph.annotator, "edge.create", "Edge", edge.pk, data)
    return edge


@transaction.atomic
def update_edge(
    edge: Edge,
    data: dict,
    subject: Node = None,
    object_node: Node = None,
    actor=None,
) -> Edge:
    if subject is not None and subject.graph_id != edge.graph_id:
        raise ValueError("Edge subject must belong to the edge graph.")
    if object_node is not None and object_node.graph_id != edge.graph_id:
        raise ValueError("Edge object must belong to the edge graph.")
    if subject is not None:
        edge.subject = subject
    if object_node is not None:
        edge.object = object_node
    edge.predicate = data.get("predicate", edge.predicate)
    edge.claim_strength = data.get("claim_strength", edge.claim_strength)
    edge.data = data
    edge.save()
    emit_audit(actor or edge.graph.annotator, "edge.update", "Edge", edge.pk, data)
    return edge


@transaction.atomic
def set_edge_source_spans(edge: Edge, spans, actor) -> None:
    """Replace the excerpts grounding *edge* without stealing another edge's spans."""
    requested = {span.pk: span for span in spans}
    current = list(edge.spans.all())

    for span in current:
        if span.pk not in requested:
            span.edge = None
            span.save(update_fields=["edge"])
            emit_audit(
                actor,
                "span.unlink",
                "TextSpan",
                span.pk,
                {"edge_id": edge.pk},
            )

    for span in requested.values():
        if span.edge_id not in {None, edge.pk}:
            continue
        if span.edge_id != edge.pk:
            span.edge = edge
            span.save(update_fields=["edge"])
            emit_audit(
                actor,
                "span.link",
                "TextSpan",
                span.pk,
                {"edge_id": edge.pk},
            )


@transaction.atomic
def delete_node(node: Node, actor) -> None:
    """Delete a node and its connected edges, recording every graph mutation."""
    connected = Edge.objects.filter(graph=node.graph).filter(
        Q(subject=node) | Q(object=node)
    )
    for edge in connected:
        emit_audit(actor, "edge.delete", "Edge", edge.pk)
        edge.delete()
    emit_audit(actor, "node.delete", "Node", node.pk)
    node.delete()


def advance_edge_status(edge: Edge, actor) -> Edge:
    """Human-only status advancement: draft→complete."""
    transitions = {
        Edge.STATUS_DRAFT: Edge.STATUS_COMPLETE,
    }
    context = transaction.atomic() if actor is not None else nullcontext()
    with context:
        if edge.status in transitions:
            old_status = edge.status
            edge.status = transitions[edge.status]
            edge.save(update_fields=["status"])
            if actor is not None:
                emit_audit(
                    actor,
                    "edge.advance",
                    "Edge",
                    edge.pk,
                    {"from": old_status, "to": edge.status},
                )
    return edge


def adjudicate_edge(edge: Edge, actor) -> Edge:
    """Reviewer-only advancement: complete→reviewed or reviewed→gold."""
    transitions = {
        Edge.STATUS_COMPLETE: Edge.STATUS_REVIEWED,
        Edge.STATUS_REVIEWED: Edge.STATUS_GOLD,
    }
    context = transaction.atomic() if actor is not None else nullcontext()
    with context:
        if edge.status in transitions:
            old_status = edge.status
            edge.status = transitions[edge.status]
            edge.save(update_fields=["status"])
            if actor is not None:
                emit_audit(
                    actor,
                    "edge.adjudicate",
                    "Edge",
                    edge.pk,
                    {"from": old_status, "to": edge.status},
                )
    return edge


# ── Sessions ──────────────────────────────────────────────────────────────────


@transaction.atomic
def open_session(assignment, annotator) -> "WorkSession":
    """Return the current open WorkSession, creating one if needed."""
    if assignment.annotator_id != annotator.pk:
        raise ValueError("WorkSession annotator must own the assignment.")
    assignment = type(assignment).objects.select_for_update().get(pk=assignment.pk)
    session = WorkSession.objects.filter(
        assignment=assignment,
        annotator=annotator,
        ended_at__isnull=True,
    ).first()
    if session is None:
        session = WorkSession.objects.create(assignment=assignment, annotator=annotator)
        emit_audit(annotator, "session.open", "WorkSession", session.pk)
    return session


def heartbeat(session, active_delta: int, idle_delta: int) -> None:
    """Accumulate time deltas sent by the client heartbeat."""
    from django.db.models import F

    WorkSession.objects.filter(pk=session.pk, ended_at__isnull=True).update(
        active_seconds=F("active_seconds") + max(0, active_delta),
        idle_seconds=F("idle_seconds") + max(0, idle_delta),
    )
    session.refresh_from_db()


@transaction.atomic
def close_session(session) -> None:
    """Mark a session ended and record wall-clock open_seconds."""
    from django.utils import timezone

    session.refresh_from_db()
    if session.ended_at is not None:
        return
    now = timezone.now()
    open_sec = int((now - session.started_at).total_seconds())
    WorkSession.objects.filter(pk=session.pk).update(
        ended_at=now,
        open_seconds=open_sec,
    )
    session.refresh_from_db()
    emit_audit(
        session.annotator,
        "session.close",
        "WorkSession",
        session.pk,
        {
            "active_seconds": session.active_seconds,
            "open_seconds": session.open_seconds,
        },
    )


# ── Audit ─────────────────────────────────────────────────────────────────────


def emit_audit(
    actor, action: str, target_type: str, target_id="", diff: dict = None
) -> None:
    from apps.audit.models import AuditEvent

    AuditEvent.objects.create(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        diff=diff or {},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _derive_name(data: dict) -> str:
    parts = [
        data.get("entity_type", ""),
        data.get("entity_term", ""),
        data.get("variable_attribute", ""),
    ]
    name = " — ".join(p for p in parts if p)
    return name or "Unnamed node"


def _unflatten_post(post_dict: dict) -> dict:
    """Convert __ -separated POST keys to nested dicts.

    {'mediation__has_mediator': 'true'} → {'mediation': {'has_mediator': 'true'}}
    """
    result: dict = {}
    for key, value in post_dict.items():
        if "__" in key:
            parent, child = key.split("__", 1)
            if parent not in result:
                result[parent] = {}
            if isinstance(result[parent], dict):
                result[parent][child] = value
        else:
            result[key] = value
    return result
