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
    sign: int   # +1, -1, or 0
    strength: float
    weight: float   # sign * strength, rounded to 4 dp


_STRENGTH_WEIGHT: dict[str, float] = {
    "necessary_condition": 1.0,
    "sufficient_condition": 1.0,
    "strong_tendency": 0.8,
    "tendency": 0.6,
    "weak_tendency": 0.3,
}
_STRENGTH_DEFAULT = 0.5

_FCM_SIGN_MAP = {"+": 1, "-": -1, "?": 0}


def _predicate_annotations(schema_yaml: str) -> dict[str, dict[str, str]]:
    """Extract per-predicate rosetta_template and fcm_sign from the schema."""
    sv = SchemaView(schema_yaml)
    enum = sv.get_enum("PredicateEnum")
    out: dict[str, dict[str, str]] = {}
    if enum is None:
        return out
    for pv_name, pv in enum.permissible_values.items():
        ann: dict[str, str] = {}
        for k, v in (pv.annotations or {}).items():
            ann[str(k)] = str(v.value) if hasattr(v, "value") else str(v)
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
