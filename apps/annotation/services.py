"""Service layer for annotation writes. All ORM mutations go through here."""

from .models import CausalGraph, Edge, Node


# ── Graph ─────────────────────────────────────────────────────────────────────


def create_graph(document, annotator, schema_version) -> CausalGraph:
    return CausalGraph.objects.create(
        document=document,
        annotator=annotator,
        schema_version=schema_version,
    )


# ── Nodes ─────────────────────────────────────────────────────────────────────


def create_node(graph: CausalGraph, data: dict, origin: str = Node.ORIGIN_HUMAN) -> Node:
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
    return node


def update_node(node: Node, data: dict) -> Node:
    node.name = data.get("name", "").strip() or _derive_name(data)
    node.category = data.get("entity_type", node.category)
    node.data = data
    node.save(update_fields=["name", "category", "data"])
    return node


# ── Edges ─────────────────────────────────────────────────────────────────────


def create_edge(
    graph: CausalGraph,
    subject: Node,
    object_node: Node,
    data: dict,
    origin: str = Edge.ORIGIN_HUMAN,
) -> Edge:
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
    return edge


def update_edge(
    edge: Edge,
    data: dict,
    subject: Node = None,
    object_node: Node = None,
) -> Edge:
    if subject is not None:
        edge.subject = subject
    if object_node is not None:
        edge.object = object_node
    edge.predicate = data.get("predicate", edge.predicate)
    edge.claim_strength = data.get("claim_strength", edge.claim_strength)
    edge.data = data
    edge.save()
    return edge


def advance_edge_status(edge: Edge, actor) -> Edge:
    """Human-only status advancement: draft→complete."""
    transitions = {
        Edge.STATUS_DRAFT: Edge.STATUS_COMPLETE,
    }
    if edge.status in transitions:
        edge.status = transitions[edge.status]
        edge.save(update_fields=["status"])
    return edge


def adjudicate_edge(edge: Edge, actor) -> Edge:
    """Reviewer-only advancement: complete→reviewed or reviewed→gold."""
    transitions = {
        Edge.STATUS_COMPLETE: Edge.STATUS_REVIEWED,
        Edge.STATUS_REVIEWED: Edge.STATUS_GOLD,
    }
    if edge.status in transitions:
        edge.status = transitions[edge.status]
        edge.save(update_fields=["status"])
    return edge


# ── Sessions ──────────────────────────────────────────────────────────────────


def open_session(assignment, annotator) -> "WorkSession":
    """Return the current open WorkSession, creating one if needed."""
    from .models import WorkSession

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

    from .models import WorkSession

    WorkSession.objects.filter(pk=session.pk).update(
        active_seconds=F("active_seconds") + max(0, active_delta),
        idle_seconds=F("idle_seconds") + max(0, idle_delta),
    )
    session.refresh_from_db()


def close_session(session) -> None:
    """Mark a session ended and record wall-clock open_seconds."""
    from django.utils import timezone

    from .models import WorkSession

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
        {"active_seconds": session.active_seconds, "open_seconds": session.open_seconds},
    )


# ── Audit ─────────────────────────────────────────────────────────────────────


def emit_audit(actor, action: str, target_type: str, target_id="", diff: dict = None) -> None:
    try:
        from apps.audit.models import AuditEvent

        AuditEvent.objects.create(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            diff=diff or {},
        )
    except Exception:
        pass


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
