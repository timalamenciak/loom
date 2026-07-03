"""
Deterministic rendering from a serialized CAMO graph dict.

Rosetta Statements — natural-language edge summaries derived from the
  `rosetta_template` annotation on PredicateEnum permissible values.

FCM weights — signed numeric weights derived from the `fcm_sign` annotation
  on PredicateEnum and the claim_strength value of each edge.

Both operate on the plain-dict output of serialize_graph(), not Django models,
so they work equally for the web views and the management commands.
"""

from __future__ import annotations

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
