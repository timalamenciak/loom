"""
Serialize a CausalGraph Django model instance to a CAMO-compatible Python dict.

Output is YAML-ready: nested structures are plain dicts/lists, empty/null values
are stripped, and numeric slots are cast to their schema-correct Python types.
Provenance (including SHA-256) is computed separately by build_provenance().
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from linkml_runtime.utils.schemaview import SchemaView

from loom import __version__

EXPORTER_VERSION = f"loom-{__version__}"


def _schema_slot_ranges(schema_yaml: str) -> dict[str, str]:
    """Return slot ranges from the graph-pinned schema."""
    view = SchemaView(schema_yaml)
    return {
        name: (slot.range or "string").lower()
        for name, slot in view.all_slots().items()
    }


def _cast(slot_name: str, value, slot_ranges: dict[str, str] | None = None):
    """Return value cast to the schema-correct Python type."""
    if value is None or value == "":
        return None
    slot_range = (slot_ranges or {}).get(slot_name, "")
    if slot_range in {"integer", "int"}:
        try:
            return int(value)
        except (ValueError, TypeError):
            return value
    if slot_range in {"float", "double", "decimal"}:
        try:
            return float(value)
        except (ValueError, TypeError):
            return value
    if slot_range in {"boolean", "bool"}:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return value


def _clean(d: dict, slot_ranges: dict[str, str] | None = None) -> dict:
    """Strip None/empty-string values recursively; cast numeric fields by slot name."""
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, dict):
            cleaned = _clean(v, slot_ranges)
            if cleaned:
                out[k] = cleaned
        elif isinstance(v, list):
            cleaned = []
            for item in v:
                if isinstance(item, dict):
                    nested = _clean(item, slot_ranges)
                    if nested:
                        cleaned.append(nested)
                else:
                    casted = _cast(k, item, slot_ranges)
                    if casted is not None and casted != "":
                        cleaned.append(casted)
            if cleaned:
                out[k] = cleaned
        else:
            casted = _cast(k, v, slot_ranges)
            if casted is not None and casted != "":
                out[k] = casted
    return out


def _serialize_node(node, slot_ranges: dict[str, str]) -> dict:
    base = {"node_id": node.node_id, "name": node.name}
    merged = {**node.data, **base}
    return _clean(merged, slot_ranges)


def _serialize_spans(edge, slot_ranges: dict[str, str]) -> list[dict]:
    out = []
    for s in edge.spans.all().order_by("start_char"):
        span = _clean(
            {"start_char": s.start_char, "end_char": s.end_char, "span_text": s.text},
            slot_ranges,
        )
        if span:
            out.append(span)
    return out


def _serialize_edge(
    edge, slot_ranges: dict[str, str], source_document: dict | None = None
) -> dict:
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

    # Inject the graph-level source_document (already merged with doc bib fields)
    if source_document:
        merged["source_document"] = source_document

    result = _clean(merged, slot_ranges)

    # DB-linked spans are authoritative; replace any JSONB source_spans
    spans = _serialize_spans(edge, slot_ranges)
    if spans:
        result["source_spans"] = spans

    return result


def _serialize_source_document(document, slot_ranges: dict[str, str]) -> dict:
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
    return _clean(d, slot_ranges)


def _build_graph_source_document(graph, slot_ranges: dict[str, str]) -> dict:
    """
    Merge doc bib fields, project rollup values, and annotator-supplied data.
    Priority (highest wins): annotator saved > rolled up > doc bib fields.
    """
    document = graph.document
    doc_bib: dict = {}
    if document.doi:
        doc_bib["doi"] = document.doi
    if document.title:
        doc_bib["title"] = document.title
    if document.authors:
        doc_bib["authors"] = list(document.authors)
    if document.year:
        doc_bib["year"] = document.year
    if document.journal:
        doc_bib["journal"] = document.journal

    rules = getattr(document.project, "source_document_rollup", None) or []
    rolled: dict = {}
    if rules:
        from apps.annotation.rollup import roll_up_source_document

        nodes_data = list(graph.nodes.values_list("data", flat=True))
        edges_data = list(graph.edges.values_list("data", flat=True))
        rolled = roll_up_source_document(nodes_data, edges_data, rules)

    annotator_data = graph.source_document or {}
    return _clean({**doc_bib, **rolled, **annotator_data}, slot_ranges)


def serialize_graph(graph) -> dict:
    """
    Return a CAMO-compatible dict for a CausalGraph instance.

    Does not include provenance — caller adds it with build_provenance() after
    serializing to YAML and computing the SHA-256.
    """
    slot_ranges = _schema_slot_ranges(graph.schema_version.linkml_yaml)
    nodes = [
        _serialize_node(n, slot_ranges) for n in graph.nodes.all().order_by("name")
    ]
    # Build source_document once and stamp it onto every edge
    source_document = _build_graph_source_document(graph, slot_ranges)
    edges = [
        _serialize_edge(e, slot_ranges, source_document=source_document)
        for e in graph.edges.select_related("subject", "object")
        .all()
        .order_by("-created_at")
    ]
    return {
        "graph_id": str(graph.pk),
        "source_document": _serialize_source_document(graph.document, slot_ranges),
        "nodes": nodes,
        "edges": edges,
    }


def build_provenance(
    graph,
    yaml_bytes: bytes,
    *,
    ontology_snapshot_id: str | None = None,
) -> dict:
    """
    Build GraphProvenance dict.

    SHA-256 is computed over yaml_bytes — the caller passes the serialized YAML
    produced *before* provenance is embedded, so the hash is reproducible.
    """
    if ontology_snapshot_id is None:
        snapshot = getattr(graph, "ontology_snapshot", None)
        if snapshot:
            fingerprint = snapshot.manifest_sha256 or f"legacy-{snapshot.pk}"
            ontology_snapshot_id = f"snapshot-{snapshot.pk}:{fingerprint}"
        else:
            ontology_snapshot_id = "none"
    return {
        "schema_version_str": graph.schema_version.version,
        "ontology_snapshot_id": ontology_snapshot_id,
        "exporter_version": EXPORTER_VERSION,
        "export_sha256": hashlib.sha256(yaml_bytes).hexdigest(),
        "exported_at": datetime.now(tz=timezone.utc).isoformat(),
    }
