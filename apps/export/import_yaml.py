"""Parse an uploaded YAML file into flat node/edge row dicts.

Input shape mirrors ``apps.export.serializer.serialize_graph()``'s output —
nodes/edges keyed by node_id/edge_id, edges referencing node_id via
subject/object. ``provenance`` and ``source_document`` are ignored: this
importer is scoped to nodes + edges only (a graph's bibliographic
source_document has its own surface, ``update_graph_source_document``).
"""

from __future__ import annotations

import yaml

from .graph_import import ImportParseError


def parse_yaml_import(file_obj) -> tuple[list[dict], list[dict]]:
    try:
        raw = yaml.safe_load(file_obj.read())
    except yaml.YAMLError as exc:
        raise ImportParseError(f"Could not parse YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ImportParseError(
            "Top-level YAML content must be a mapping with 'nodes'/'edges' keys."
        )

    nodes = raw.get("nodes") or []
    edges = raw.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ImportParseError("'nodes' and 'edges' must be lists.")
    for item in nodes + edges:
        if not isinstance(item, dict):
            raise ImportParseError("Each node/edge entry must be a mapping.")

    return nodes, edges
