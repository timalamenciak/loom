"""
Deterministic rendering from a serialized CAMO graph dict.

Rosetta Statements — natural-language edge summaries derived from the
  `rosetta_template` annotation on PredicateEnum permissible values.

FCM weights — signed numeric weights derived from the `fcm_sign` annotation
  on PredicateEnum and the claim_strength value of each edge.

Graph preview — a JSON-ready node/edge payload for the in-workbench vis-network
  preview. A read-only visualization adapter (no provenance, no schema needed):
  same category of deterministic computed output as the two renderers above.

All operate on the plain-dict output of serialize_graph(), not Django models,
so they work equally for the web views and the management commands.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from linkml_runtime.utils.schemaview import SchemaView


@dataclass
class RosettaStatement:
    edge_id: str
    subject_name: str
    predicate: str
    object_name: str
    statement: str
    certainty_grade: float | None


@dataclass
class FCMWeight:
    edge_id: str
    predicate: str
    claim_strength: str
    sign: int  # +1, -1, or 0
    strength: float
    weight: float  # sign * strength, rounded to 4 dp


_STRENGTH_WEIGHT: dict[str, float] = {
    "necessary_condition": 1.0,
    "sufficient_condition": 1.0,
    "strong_tendency": 0.8,
    "tendency": 0.6,
    "weak_tendency": 0.3,
}
_STRENGTH_DEFAULT = 0.5

_FCM_SIGN_MAP = {"+": 1, "-": -1, "?": 0}


def _normalize_fcm_sign(ann: dict[str, str]) -> str:
    """Return a "+"/"-"/"?" sign glyph regardless of which CAMO generation
    the predicate enum comes from.

    CAMO 0.4.x annotated each PredicateEnum value with a single-character
    fcm_sign glyph directly. CAMO 0.7.x renamed the enum to
    CausalPredicateEnum and replaced fcm_sign with a numeric
    fcm_default_weight annotation instead — this derives the same glyph from
    that weight's sign so the rest of render_fcm doesn't need to care which
    schema generation produced it.
    """
    if "fcm_sign" in ann:
        return ann["fcm_sign"]
    weight_str = ann.get("fcm_default_weight")
    if weight_str is not None:
        try:
            weight = float(weight_str)
        except ValueError:
            return "?"
        if weight > 0:
            return "+"
        if weight < 0:
            return "-"
    return "?"


def _predicate_annotations(schema_yaml: str) -> dict[str, dict[str, str]]:
    """Extract per-predicate rosetta_template and a normalized fcm_sign from
    the schema's predicate enum.

    A graph stays pinned to whichever schema version it was annotated under
    (CausalGraph.schema_version), so this must keep rendering graphs
    annotated under both the old PredicateEnum and the current
    CausalPredicateEnum indefinitely, not just the latest schema.
    """
    sv = SchemaView(schema_yaml)
    enum = sv.get_enum("CausalPredicateEnum") or sv.get_enum("PredicateEnum")
    out: dict[str, dict[str, str]] = {}
    if enum is None:
        return out
    for pv_name, pv in enum.permissible_values.items():
        ann: dict[str, str] = {}
        for k, v in (pv.annotations or {}).items():
            ann[str(k)] = str(v.value) if hasattr(v, "value") else str(v)
        ann["fcm_sign"] = _normalize_fcm_sign(ann)
        out[pv_name] = ann
    return out


def _node_names(data: dict) -> dict[str, str]:
    return {n["node_id"]: n.get("name", n["node_id"]) for n in data.get("nodes", [])}


def render_rosetta(data: dict, schema_yaml: str) -> list[RosettaStatement]:
    """Return a RosettaStatement for every edge with a rosetta_template."""
    pred_anns = _predicate_annotations(schema_yaml)
    names = _node_names(data)
    out: list[RosettaStatement] = []

    for edge in data.get("edges", []):
        predicate = edge.get("predicate", "")
        template = pred_anns.get(predicate, {}).get("rosetta_template")
        if not template:
            continue

        subject_name = names.get(edge.get("subject", ""), edge.get("subject", "?"))
        object_name = names.get(edge.get("object", ""), edge.get("object", "?"))
        stmt = template.format(subject=subject_name, object=object_name)

        certainty = edge.get("certainty_grade")
        if certainty is not None:
            try:
                if float(certainty) < 0.5:
                    stmt = f"Possibly: {stmt[0].lower()}{stmt[1:]}"
            except (ValueError, TypeError):
                pass

        out.append(
            RosettaStatement(
                edge_id=edge.get("edge_id", ""),
                subject_name=subject_name,
                predicate=predicate,
                object_name=object_name,
                statement=stmt,
                certainty_grade=certainty,
            )
        )
    return out


def render_fcm(data: dict, schema_yaml: str) -> list[FCMWeight]:
    """Return FCMWeight for every edge that has a predicate."""
    pred_anns = _predicate_annotations(schema_yaml)
    out: list[FCMWeight] = []

    for edge in data.get("edges", []):
        predicate = edge.get("predicate", "")
        if not predicate:
            continue
        fcm_sign_str = pred_anns.get(predicate, {}).get("fcm_sign", "?")
        sign = _FCM_SIGN_MAP.get(fcm_sign_str, 0)
        claim_strength = edge.get("claim_strength", "")
        strength = _STRENGTH_WEIGHT.get(claim_strength, _STRENGTH_DEFAULT)
        out.append(
            FCMWeight(
                edge_id=edge.get("edge_id", ""),
                predicate=predicate,
                claim_strength=claim_strength,
                sign=sign,
                strength=strength,
                weight=round(sign * strength, 4),
            )
        )
    return out


# ── Graph preview ────────────────────────────────────────────────────────────
#
# Turns serialize_graph() output into a vis-network payload for the workbench
# preview pane. Schema-agnostic on purpose (CLAUDE.md principle 1): no CAMO slot
# is required — node grouping and edge labelling fall back through ordered
# key-probe lists to a generic "unspecified", so an in-progress graph with
# half-filled nodes/edges still renders. Ported in structure from the standalone
# linkml-graph-viewer tool, but written for Loom's real serialized shape: nodes
# are keyed on `node_id` and edges link via `subject`/`object` == `node_id`
# (never the CURIE `id` that also rides along inside node.data).

_PREVIEW_NODE_GROUP_KEYS = ("entity_type", "category", "node_type", "type", "class")
_PREVIEW_EDGE_LABEL_KEYS = ("predicate", "relation", "relationship", "edge_type")
_PREVIEW_SUBJECT_KEYS = ("subject", "source", "from")
_PREVIEW_OBJECT_KEYS = ("object", "target", "to")
_PREVIEW_UNSPECIFIED = "unspecified"
_PREVIEW_MISSING = "missing"


def _first_present(record: dict, keys: tuple[str, ...]) -> str:
    """First key in *keys* whose value is a non-empty scalar."""
    for key in keys:
        value = record.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return ""


def _compact_id(value: str) -> str:
    """Human-ish short form of a CURIE / URI / slug identifier."""
    value = str(value)
    if ":" in value:
        value = value.rsplit(":", 1)[-1]
    if "/" in value:
        value = value.rstrip("/").rsplit("/", 1)[-1]
    return value or str(value)


def render_graph_preview(data: dict) -> dict:
    """Adapt a serialize_graph() dict into a JSON-ready vis-network payload.

    Returns nodes/edges lists plus group vocabularies + counts and a list of
    human-readable warnings (dangling endpoints, empty graph, malformed
    records). Never raises on a partial/in-progress graph.
    """
    warnings: list[str] = []
    node_group_counts: Counter[str] = Counter()
    edge_group_counts: Counter[str] = Counter()

    nodes_out: list[dict] = []
    node_index: dict[str, int] = {}

    for raw in data.get("nodes", []):
        if not isinstance(raw, dict):
            warnings.append("Skipped a node that was not a mapping.")
            continue
        nid = raw.get("node_id") or raw.get("id") or raw.get("name")
        if not nid:
            warnings.append("Skipped a node with no identifier.")
            continue
        nid = str(nid)
        group = _first_present(raw, _PREVIEW_NODE_GROUP_KEYS) or _PREVIEW_UNSPECIFIED
        label = raw.get("name") or _compact_id(nid)
        node = {
            "id": nid,
            "label": str(label),
            "group": group,
            "properties": raw,
            "placeholder": False,
        }
        if nid in node_index:
            warnings.append(f"Duplicate node id '{nid}' — showing the last one.")
            prev = nodes_out[node_index[nid]]
            node_group_counts[prev["group"]] -= 1
            nodes_out[node_index[nid]] = node
        else:
            node_index[nid] = len(nodes_out)
            nodes_out.append(node)
        node_group_counts[group] += 1

    edges_out: list[dict] = []

    for i, raw in enumerate(data.get("edges", [])):
        if not isinstance(raw, dict):
            warnings.append("Skipped an edge that was not a mapping.")
            continue
        edge_ref = raw.get("edge_id") or f"#{i + 1}"
        subject = _first_present(raw, _PREVIEW_SUBJECT_KEYS)
        obj = _first_present(raw, _PREVIEW_OBJECT_KEYS)
        if not subject or not obj:
            warnings.append(f"Skipped edge {edge_ref}: missing subject or object.")
            continue

        for endpoint in (subject, obj):
            if endpoint not in node_index:
                node_index[endpoint] = len(nodes_out)
                nodes_out.append(
                    {
                        "id": endpoint,
                        "label": _compact_id(endpoint),
                        "group": _PREVIEW_MISSING,
                        "properties": {
                            "id": endpoint,
                            "note": "Referenced by an edge but not defined as a node.",
                        },
                        "placeholder": True,
                    }
                )
                node_group_counts[_PREVIEW_MISSING] += 1
                warnings.append(
                    f"Edge {edge_ref} references undefined node '{endpoint}'."
                )

        predicate = (
            _first_present(raw, _PREVIEW_EDGE_LABEL_KEYS) or _PREVIEW_UNSPECIFIED
        )
        edges_out.append(
            {
                "id": str(raw.get("edge_id") or f"edge-{i + 1}"),
                "from": subject,
                "to": obj,
                "label": predicate,
                "group": predicate,
                "properties": raw,
            }
        )
        edge_group_counts[predicate] += 1

    if not nodes_out and not edges_out:
        warnings.append("This graph is empty — add nodes and edges to see a preview.")

    return {
        "graph_id": data.get("graph_id"),
        "source_document": data.get("source_document") or {},
        "nodes": nodes_out,
        "edges": edges_out,
        "node_groups": sorted(g for g, c in node_group_counts.items() if c > 0),
        "edge_groups": sorted(edge_group_counts),
        "node_group_counts": {
            g: c for g, c in sorted(node_group_counts.items()) if c > 0
        },
        "edge_group_counts": dict(sorted(edge_group_counts.items())),
        "counts": {"nodes": len(nodes_out), "edges": len(edges_out)},
        "warnings": warnings,
    }
