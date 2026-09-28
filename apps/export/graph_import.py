"""Format-agnostic bulk-import core: diff uploaded node/edge rows against a
graph's current state, without writing anything, then apply an approved plan.

Excel and YAML readers (import_excel.py, import_yaml.py) both hand off plain
``node_rows``/``edge_rows`` (lists of flat dicts) here — this module never
knows which format they came from, and never hardcodes a CAMO slot name:
column/field validation routes entirely through ``bind_form_data`` against
the graph's pinned schema, exactly like the live annotation form.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from apps.annotation.models import CausalGraph, Edge, Node
from apps.annotation.services import (
    EDGE_MANAGED_SLOTS,
    NODE_MANAGED_SLOTS,
    create_edge,
    create_node,
    delete_edge,
    delete_node,
    emit_import_audit,
    update_edge,
    update_node,
)
from apps.export.serializer import serialize_graph

VERDICT_CREATE = "create"
VERDICT_UPDATE = "update"
VERDICT_NOOP = "noop"
VERDICT_WOULD_DELETE = "would_delete"
VERDICT_ERROR = "error"

_ALL_VERDICTS = (
    VERDICT_CREATE,
    VERDICT_UPDATE,
    VERDICT_NOOP,
    VERDICT_WOULD_DELETE,
    VERDICT_ERROR,
)

# _annotate_with_orcid() (apps.annotation.services) overwrites this key with
# the *importing* actor's identity on every create/update call regardless of
# what the row says. It also isn't a CAMO schema slot at all (it's a Loom-
# injected JSONB key), so a row from a real export — which legitimately
# carries whatever "annotator" serialize_graph() wrote — must never be
# handed to bind_form_data() with this key still attached, or every
# re-imported row would fail as an "unrecognized field." Stripped from both
# the bind_form_data payload and the diff comparison.
_DIFF_IGNORED_KEYS = frozenset({"annotator"})

_EDGE_REF_KEYS = frozenset({"subject_node_id", "object_node_id"})


class ImportParseError(ValueError):
    """Raised when an uploaded file cannot be parsed into node/edge rows."""


@dataclass
class RowResult:
    sheet: str  # "Nodes" | "Edges"
    row_number: int  # 1-based; 0 for a WOULD_DELETE row synthesized from the baseline
    id_value: str  # node_id or edge_id
    verdict: str
    bound_data: dict[str, Any] | None = (
        None  # bind_form_data() output; None for NOOP/ERROR/WOULD_DELETE
    )
    changed_fields: dict[str, tuple[Any, Any]] = field(
        default_factory=dict
    )  # UPDATE only
    errors: list[str] = field(default_factory=list)  # ERROR only
    subject_node_id: str | None = None  # edges only
    object_node_id: str | None = None  # edges only


@dataclass
class ImportPlan:
    graph_id: int
    uploaded_by_id: int
    format: str  # "xlsx" | "yaml"
    full_sync: bool
    source_sha256: str
    node_results: list[RowResult] = field(default_factory=list)
    edge_results: list[RowResult] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for label, results in (
            ("nodes", self.node_results),
            ("edges", self.edge_results),
        ):
            for verdict in _ALL_VERDICTS:
                counts[f"{label}_{verdict}"] = sum(
                    1 for r in results if r.verdict == verdict
                )
        return counts


def _flatten_row(row: dict) -> dict:
    """Flatten a row that may carry nested dict/list-of-dict values (as
    produced by serialize_graph()/YAML, or a JSON-string Excel cell for a
    nested fieldset slot — see import_excel.py) into the "__"-joined flat
    key scheme bind_form_data() expects, mirroring how the live annotation
    form POSTs nested fieldset values.
    """
    flat: dict = {}
    for key, value in row.items():
        _flatten_into(flat, key, value)
    return flat


def _flatten_into(flat: dict, prefix: str, value) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _flatten_into(flat, f"{prefix}__{key}", nested)
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        for index, item in enumerate(value):
            for key, nested in item.items():
                _flatten_into(flat, f"{prefix}__{index}__{key}", nested)
    else:
        flat[prefix] = value


def _diff(
    bound_data: dict, baseline: dict | None, *, ignored: frozenset
) -> tuple[str, dict]:
    """Compare bound_data to the baseline row (or None if not yet on the graph).

    *ignored* must include the caller's managed-slot set (node_id/edge_id/
    subject/object/source_spans/id) — serialize_graph()'s baseline dict
    carries those, bind_form_data()'s output never does (they're excluded
    from binding), so without this every row with e.g. grounding spans
    would spuriously diff as UPDATE.
    """
    if baseline is None:
        return VERDICT_CREATE, {}
    changed: dict[str, tuple[Any, Any]] = {}
    for key in (set(bound_data) | set(baseline)) - ignored:
        old, new = baseline.get(key), bound_data.get(key)
        if old != new:
            changed[key] = (old, new)
    return (VERDICT_UPDATE, changed) if changed else (VERDICT_NOOP, {})


def _binding_error_list(errors: dict[str, list[str]]) -> list[str]:
    return [
        f"{field_name}: {msg}" for field_name, msgs in errors.items() for msg in msgs
    ]


def _strip_autofilled_slots(bound_data: dict, flat_row: dict) -> dict:
    """Drop bound_data keys the row never mentioned at all.

    bind_form_data() fills every unspecified scalar slot with its schema
    ifabsent default — correct for the live HTML form, which always posts
    every field. An import row is routinely column-sparse instead (the
    exporter's own YAML drops unset values via serializer._clean(), and a
    hand-edited file rarely repeats every column) — for import, an omitted
    column means "leave unspecified", not "reset to default". Otherwise
    re-uploading an unedited export would flip every implicit-default enum
    field and report a false UPDATE on every row.

    Presence is checked at top-level slot granularity (nested-fieldset
    subslots the row didn't mention can still pick up their own ifabsent
    default once the parent slot is present) — a reasonable scope limit,
    not a round-trip-breaking one.
    """
    present_top_level = {key.split("__", 1)[0] for key in flat_row}
    return {k: v for k, v in bound_data.items() if k in present_top_level}


def build_import_plan(
    graph: CausalGraph,
    node_rows: list[dict],
    edge_rows: list[dict],
    *,
    schema_view,
    full_sync: bool,
    source_sha256: str,
    format: str,  # noqa: A002 - matches the plan's public signature
    uploaded_by_id: int,
) -> ImportPlan:
    baseline = serialize_graph(graph)
    baseline_nodes = {n["node_id"]: n for n in baseline["nodes"]}
    baseline_edges = {e["edge_id"]: e for e in baseline["edges"]}

    plan = ImportPlan(
        graph_id=graph.pk,
        uploaded_by_id=uploaded_by_id,
        format=format,
        full_sync=full_sync,
        source_sha256=source_sha256,
    )

    # Node reference resolution (both directions): subject_node_id/
    # object_node_id may match a node row elsewhere in this file, or a node
    # already on the graph. Seed with the baseline so upsert-only imports —
    # where most edges reference nodes that already exist and aren't
    # repeated in the file — resolve correctly.
    resolved_node_ids: set[str] = set(baseline_nodes)
    # Every node_id that appeared as a row in this file, valid or not — used
    # only to decide full-sync deletions below. A row that fails validation
    # is still *present* in the file; its existing baseline node must be
    # left alone, not deleted as "absent from the file" (see
    # _mark_full_sync_deletions). Deliberately broader than resolved_node_ids,
    # which only gains an id once its row actually binds successfully.
    touched_node_ids: set[str] = set()
    seen_node_ids: set[str] = set()

    for row_number, row in enumerate(node_rows, start=1):
        node_id = str(row.get("node_id") or "").strip()
        if not node_id:
            plan.node_results.append(
                RowResult(
                    sheet="Nodes",
                    row_number=row_number,
                    id_value="",
                    verdict=VERDICT_ERROR,
                    errors=["node_id is required."],
                )
            )
            continue

        touched_node_ids.add(node_id)
        if node_id in seen_node_ids:
            plan.node_results.append(
                RowResult(
                    sheet="Nodes",
                    row_number=row_number,
                    id_value=node_id,
                    verdict=VERDICT_ERROR,
                    errors=[
                        f"Duplicate node_id {node_id!r} in this file; only the "
                        "first occurrence is applied."
                    ],
                )
            )
            continue
        seen_node_ids.add(node_id)

        payload = {
            k: v
            for k, v in row.items()
            if k not in NODE_MANAGED_SLOTS and k not in _DIFF_IGNORED_KEYS
        }
        flat_payload = _flatten_row(payload)
        binding = schema_view.bind_form_data(
            "CausalNode", flat_payload, excluded_slots=NODE_MANAGED_SLOTS
        )
        if not binding.is_valid:
            plan.node_results.append(
                RowResult(
                    sheet="Nodes",
                    row_number=row_number,
                    id_value=node_id,
                    verdict=VERDICT_ERROR,
                    errors=_binding_error_list(binding.errors),
                )
            )
            continue

        bound_data = _strip_autofilled_slots(binding.data, flat_payload)
        verdict, changed = _diff(
            bound_data,
            baseline_nodes.get(node_id),
            ignored=NODE_MANAGED_SLOTS | _DIFF_IGNORED_KEYS,
        )
        plan.node_results.append(
            RowResult(
                sheet="Nodes",
                row_number=row_number,
                id_value=node_id,
                verdict=verdict,
                bound_data=bound_data,
                changed_fields=changed,
            )
        )
        resolved_node_ids.add(node_id)

    seen_edge_ids: set[str] = set()

    for row_number, row in enumerate(edge_rows, start=1):
        edge_id = str(row.get("edge_id") or "").strip()
        subject_id = str(row.get("subject_node_id") or row.get("subject") or "").strip()
        object_id = str(row.get("object_node_id") or row.get("object") or "").strip()

        if edge_id and edge_id in seen_edge_ids:
            plan.edge_results.append(
                RowResult(
                    sheet="Edges",
                    row_number=row_number,
                    id_value=edge_id,
                    verdict=VERDICT_ERROR,
                    errors=[
                        f"Duplicate edge_id {edge_id!r} in this file; only the "
                        "first occurrence is applied."
                    ],
                    subject_node_id=subject_id or None,
                    object_node_id=object_id or None,
                )
            )
            continue
        if edge_id:
            seen_edge_ids.add(edge_id)

        errors: list[str] = []
        if not edge_id:
            errors.append("edge_id is required.")
        if not subject_id:
            errors.append("subject_node_id is required.")
        elif subject_id not in resolved_node_ids:
            errors.append(
                f"subject_node_id {subject_id!r} does not match any node in this file or on the graph."
            )
        if not object_id:
            errors.append("object_node_id is required.")
        elif object_id not in resolved_node_ids:
            errors.append(
                f"object_node_id {object_id!r} does not match any node in this file or on the graph."
            )
        if errors:
            plan.edge_results.append(
                RowResult(
                    sheet="Edges",
                    row_number=row_number,
                    id_value=edge_id,
                    verdict=VERDICT_ERROR,
                    errors=errors,
                    subject_node_id=subject_id or None,
                    object_node_id=object_id or None,
                )
            )
            continue

        payload = {
            k: v
            for k, v in row.items()
            if k not in EDGE_MANAGED_SLOTS
            and k not in _EDGE_REF_KEYS
            and k not in _DIFF_IGNORED_KEYS
        }
        flat_payload = _flatten_row(payload)
        binding = schema_view.bind_form_data(
            "CausalEdge", flat_payload, excluded_slots=EDGE_MANAGED_SLOTS
        )
        if not binding.is_valid:
            plan.edge_results.append(
                RowResult(
                    sheet="Edges",
                    row_number=row_number,
                    id_value=edge_id,
                    verdict=VERDICT_ERROR,
                    errors=_binding_error_list(binding.errors),
                    subject_node_id=subject_id,
                    object_node_id=object_id,
                )
            )
            continue

        bound_data = _strip_autofilled_slots(binding.data, flat_payload)
        verdict, changed = _diff(
            bound_data,
            baseline_edges.get(edge_id),
            ignored=EDGE_MANAGED_SLOTS | _DIFF_IGNORED_KEYS,
        )
        # subject_node_id/object_node_id never reach bind_form_data (they're
        # resolved separately above, not schema slots on CausalEdge), so
        # _diff() above can't see a re-pointed endpoint — only the row's
        # other fields. Compare them explicitly: re-pointing only the
        # endpoints and nothing else must still be an UPDATE, not a NOOP
        # apply_import_plan() silently skips.
        baseline_edge = baseline_edges.get(edge_id)
        if baseline_edge is not None:
            if baseline_edge.get("subject") != subject_id:
                changed["subject_node_id"] = (baseline_edge.get("subject"), subject_id)
            if baseline_edge.get("object") != object_id:
                changed["object_node_id"] = (baseline_edge.get("object"), object_id)
            if changed and verdict == VERDICT_NOOP:
                verdict = VERDICT_UPDATE
        plan.edge_results.append(
            RowResult(
                sheet="Edges",
                row_number=row_number,
                id_value=edge_id,
                verdict=verdict,
                bound_data=bound_data,
                changed_fields=changed,
                subject_node_id=subject_id,
                object_node_id=object_id,
            )
        )

    if full_sync:
        _mark_full_sync_deletions(
            plan, baseline_nodes, baseline_edges, touched_node_ids
        )

    return plan


def _mark_full_sync_deletions(
    plan: ImportPlan,
    baseline_nodes: dict[str, dict],
    baseline_edges: dict[str, dict],
    touched_node_ids: set[str],
) -> None:
    for node_id in baseline_nodes:
        if node_id not in touched_node_ids:
            plan.node_results.append(
                RowResult(
                    sheet="Nodes",
                    row_number=0,
                    id_value=node_id,
                    verdict=VERDICT_WOULD_DELETE,
                )
            )

    # Include ERROR rows too, for the same reason as touched_node_ids above:
    # a row present in the file but rejected by validation must not cause
    # its pre-existing baseline edge to be independently deleted.
    touched_edge_ids = {r.id_value for r in plan.edge_results if r.id_value}
    for edge_id, edge_data in baseline_edges.items():
        if edge_id not in touched_edge_ids:
            plan.edge_results.append(
                RowResult(
                    sheet="Edges",
                    row_number=0,
                    id_value=edge_id,
                    verdict=VERDICT_WOULD_DELETE,
                    subject_node_id=edge_data.get("subject"),
                    object_node_id=edge_data.get("object"),
                )
            )

    # Orphan conflict check: an edge that survives (create/update/noop) but
    # references a node about to be deleted would be left dangling — block
    # it instead of letting the applied import leave a broken graph.
    deleted_node_ids = {
        r.id_value for r in plan.node_results if r.verdict == VERDICT_WOULD_DELETE
    }
    for row in plan.edge_results:
        if row.verdict in (VERDICT_ERROR, VERDICT_WOULD_DELETE):
            continue
        for label, endpoint_id in (
            ("subject", row.subject_node_id),
            ("object", row.object_node_id),
        ):
            if endpoint_id in deleted_node_ids:
                row.verdict = VERDICT_ERROR
                row.errors.append(
                    f"{label} node {endpoint_id!r} is not present in this file and will be "
                    "deleted under full sync; include it or remove this edge."
                )


def apply_import_plan(plan: ImportPlan, actor) -> dict[str, int]:
    """Commit an approved plan.

    Re-resolves each node_id/edge_id against the database at apply time and
    always goes through an idempotent create-or-update path, rather than
    trusting the plan's cached verdicts — those are authoritative for the
    *preview display* the user approved, not for how the write executes, so
    Apply stays safe even if the plan is a few minutes stale.
    """
    graph = CausalGraph.objects.select_related("schema_version", "annotator").get(
        pk=plan.graph_id
    )

    with transaction.atomic():
        nodes_by_id = {n.node_id: n for n in Node.objects.filter(graph=graph)}
        for row in plan.node_results:
            if row.verdict in (VERDICT_ERROR, VERDICT_WOULD_DELETE):
                continue
            existing = nodes_by_id.get(row.id_value)
            if existing is not None:
                if row.verdict == VERDICT_UPDATE:
                    nodes_by_id[row.id_value] = update_node(
                        existing, dict(row.bound_data), actor=actor
                    )
            else:
                nodes_by_id[row.id_value] = create_node(
                    graph, dict(row.bound_data or {}), actor=actor, node_id=row.id_value
                )

        edges_by_id = {e.edge_id: e for e in Edge.objects.filter(graph=graph)}
        for row in plan.edge_results:
            if row.verdict in (VERDICT_ERROR, VERDICT_WOULD_DELETE):
                continue
            subject = nodes_by_id.get(row.subject_node_id)
            object_node = nodes_by_id.get(row.object_node_id)
            if subject is None or object_node is None:
                raise ValueError(
                    f"Edge {row.id_value!r} references a node that no longer exists — "
                    "the graph changed since this import was previewed."
                )
            existing = edges_by_id.get(row.id_value)
            if existing is not None:
                if row.verdict == VERDICT_UPDATE:
                    edges_by_id[row.id_value] = update_edge(
                        existing,
                        dict(row.bound_data),
                        subject=subject,
                        object_node=object_node,
                        actor=actor,
                    )
            else:
                edges_by_id[row.id_value] = create_edge(
                    graph,
                    subject,
                    object_node,
                    dict(row.bound_data or {}),
                    actor=actor,
                    edge_id=row.id_value,
                )

        if plan.full_sync:
            # Edges first: Node.edges_as_subject/object use on_delete=PROTECT,
            # so a would-delete edge must go before its would-delete node.
            for row in plan.edge_results:
                if row.verdict != VERDICT_WOULD_DELETE:
                    continue
                edge = edges_by_id.pop(row.id_value, None)
                if edge is not None:
                    delete_edge(edge, actor)
            for row in plan.node_results:
                if row.verdict != VERDICT_WOULD_DELETE:
                    continue
                node = nodes_by_id.pop(row.id_value, None)
                if node is not None:
                    delete_node(node, actor)

        counts = plan.counts()
        emit_import_audit(
            actor, graph, format=plan.format, full_sync=plan.full_sync, counts=counts
        )

    return counts


def render_plan_text(plan: ImportPlan) -> str:
    """CLI stdout report; also the template context for import_preview.html —
    one source of truth for what a verdict means, not two renderers."""
    lines: list[str] = []
    for sheet, results in (("Nodes", plan.node_results), ("Edges", plan.edge_results)):
        for row in results:
            lines.append(_render_row_line(sheet, row))

    counts = plan.counts()
    lines.append("")
    lines.append(
        f"{len(plan.node_results)} node rows: {counts['nodes_create']} create, "
        f"{counts['nodes_update']} update, {counts['nodes_noop']} unchanged, "
        f"{counts['nodes_would_delete']} delete (full sync), {counts['nodes_error']} error"
    )
    lines.append(
        f"{len(plan.edge_results)} edge rows: {counts['edges_create']} create, "
        f"{counts['edges_update']} update, {counts['edges_noop']} unchanged, "
        f"{counts['edges_would_delete']} delete (full sync), {counts['edges_error']} error"
    )
    lines.append("")
    lines.append("Preview only — click Apply to commit, or re-upload to start over.")
    return "\n".join(lines)


def _render_row_line(sheet: str, row: RowResult) -> str:
    noun = sheet[:-1].lower()  # "Nodes" -> "node", "Edges" -> "edge"
    if row.verdict == VERDICT_ERROR:
        return f'Row {row.row_number} ({sheet}): ERROR — {"; ".join(row.errors)}'
    if row.verdict == VERDICT_WOULD_DELETE:
        return f'Row {row.row_number} ({sheet}): would DELETE {noun} "{row.id_value}" (not present in file, full sync)'
    if row.verdict == VERDICT_NOOP:
        return f'Row {row.row_number} ({sheet}): unchanged "{row.id_value}"'
    verb = "CREATE" if row.verdict == VERDICT_CREATE else "UPDATE"
    line = f'Row {row.row_number} ({sheet}): would {verb} {noun} "{row.id_value}"'
    for field_name, (old, new) in row.changed_fields.items():
        line += f"\n  {field_name}: {old!r} -> {new!r}"
    return line
