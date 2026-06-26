"""
Serialize a CausalGraph Django model instance to a CAMO-compatible Python dict.

Output is YAML-ready: nested structures are plain dicts/lists, empty/null values
are stripped, and numeric slots are cast to their schema-correct Python types.
Provenance (including SHA-256) is computed separately by build_provenance().
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

EXPORTER_VERSION = "loom-0.1.0"

# EvidentialBasis / TemporalExtent integer slots
_INTEGER_SLOTS = {"n_observations"}

# Float slots
_FLOAT_SLOTS = {
    "certainty_grade",
    "p_value",
    "effect_size",
    "confidence_interval_low",
    "confidence_interval_high",
    "lag_time_value",
    "duration_value",
}


def _cast(slot_name: str, value):
    """Return value cast to the schema-correct Python type."""
    if value is None or value == "":
        return None
    if slot_name in _INTEGER_SLOTS:
        try:
            return int(value)
        except (ValueError, TypeError):
            return value
    if slot_name in _FLOAT_SLOTS:
        try:
            return float(value)
        except (ValueError, TypeError):
            return value
    return value


def _clean(d: dict) -> dict:
    """Strip None/empty-string values recursively; cast numeric fields by slot name."""
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, dict):
            cleaned = _clean(v)
            if cleaned:
                out[k] = cleaned
        elif isinstance(v, list):
            cleaned = [item for item in v if item not in (None, "")]
            if cleaned:
                out[k] = cleaned
        else:
            casted = _cast(k, v)
            if casted is not None and casted != "":
                out[k] = casted
    return out


def _serialize_node(node) -> dict:
    base = {"node_id": node.node_id, "name": node.name}
    merged = {**node.data, **base}
    return _clean(merged)


def _serialize_spans(edge) -> list[dict]:
    out = []
    for s in edge.spans.all().order_by("start_char"):
        span = _clean({"start_char": s.start_char, "end_char": s.end_char, "span_text": s.text})
        if span:
            out.append(span)
    return out


def _serialize_edge(edge) -> dict:
    base = {
        "edge_id": edge.edge_id,
        "subject": edge.subject.node_id,
        "object": edge.object.node_id,
    }
    # JSONB data first, then DB-promoted columns win
    merged = {**edge.data, **base}
    if edge.predicate:
        merged["predicate"] = edge.predicate
    if edge.claim_strength:
        merged["claim_strength"] = edge.claim_strength

    result = _clean(merged)

    # DB-linked spans are authoritative; replace any JSONB source_spans
    spans = _serialize_spans(edge)
    if spans:
        result["source_spans"] = spans

    return result


def _serialize_source_document(document) -> dict:
    d: dict = {}
    if document.title:
        d["doc_title"] = document.title
    if document.authors:
        d["doc_authors"] = list(document.authors)
    if document.year:
        d["doc_year"] = document.year
    if document.doi:
        d["doc_doi"] = document.doi
    if document.journal:
        d["doc_journal"] = document.journal
    return d


def serialize_graph(graph) -> dict:
    """
    Return a CAMO-compatible dict for a CausalGraph instance.

    Does not include provenance — caller adds it with build_provenance() after
    serializing to YAML and computing the SHA-256.
    """
    nodes = [_serialize_node(n) for n in graph.nodes.all().order_by("name")]
    edges = [
        _serialize_edge(e)
        for e in graph.edges.select_related("subject", "object").all().order_by("-created_at")
    ]
    return {
        "graph_id": str(graph.pk),
        "source_document": _serialize_source_document(graph.document),
        "nodes": nodes,
        "edges": edges,
    }


def build_provenance(
    graph,
    yaml_bytes: bytes,
    *,
    ontology_snapshot_id: str = "none",
) -> dict:
    """
    Build GraphProvenance dict.

    SHA-256 is computed over yaml_bytes — the caller passes the serialized YAML
    produced *before* provenance is embedded, so the hash is reproducible.
    """
    return {
        "schema_version_str": graph.schema_version.version,
        "ontology_snapshot_id": ontology_snapshot_id,
        "exporter_version": EXPORTER_VERSION,
        "export_sha256": hashlib.sha256(yaml_bytes).hexdigest(),
        "exported_at": datetime.now(tz=timezone.utc).isoformat(),
    }
