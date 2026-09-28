#!/usr/bin/env python3
"""Build a standalone HTML graph viewer for LinkML-style YAML files.

The generated HTML uses vis-network for the browser-side graph rendering. By
default, vis-network assets are inlined from the installed PyVis package when
available, so the output can be opened directly as a single offline HTML file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import urllib.request
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only without PyYAML.
    raise SystemExit(
        "PyYAML is required. Install it with: python -m pip install pyyaml"
    ) from exc


VIS_VERSION = "9.1.2"
VIS_JS_CDN = (
    f"https://cdn.jsdelivr.net/npm/vis-network@{VIS_VERSION}/standalone/umd/"
    "vis-network.min.js"
)
VIS_CSS_CDN = (
    f"https://cdn.jsdelivr.net/npm/vis-network@{VIS_VERSION}/styles/"
    "vis-network.min.css"
)

ENDPOINT_PAIRS = (
    ("subject", "object"),
    ("source", "target"),
    ("from", "to"),
    ("source_id", "target_id"),
    ("start", "end"),
)

NODE_GROUP_KEYS = (
    "entity_type",
    "type",
    "category",
    "class",
    "node_type",
    "kind",
)

EDGE_LABEL_KEYS = (
    "predicate",
    "relation",
    "relationship",
    "edge_type",
    "type",
    "label",
    "name",
)


def json_ready(value: Any) -> Any:
    """Convert YAML-loaded values to data that json.dumps can serialize."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_ready(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, set):
        return [json_ready(item) for item in sorted(value, key=str)]
    return str(value)


def safe_json_for_script(value: Any) -> str:
    text = json.dumps(json_ready(value), ensure_ascii=False, indent=2)
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("</", "<\\/")
    )


def scalar_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return fallback


def display_name(properties: dict[str, Any], fallback: str) -> str:
    for key in ("name", "title", "label", "id"):
        value = scalar_text(properties.get(key))
        if value:
            return value
    return fallback


def compact_identifier(value: str) -> str:
    value = str(value)
    if ":" in value:
        return value.rsplit(":", 1)[-1]
    if "/" in value:
        return value.rstrip("/").rsplit("/", 1)[-1]
    return value


def wrapped_label(label: str, width: int = 24, max_lines: int = 4) -> str:
    label = " ".join(str(label).split())
    if len(label) <= width:
        return label
    lines = textwrap.wrap(
        label,
        width=width,
        break_long_words=False,
        break_on_hyphens=True,
        max_lines=max_lines,
        placeholder="...",
    )
    return "\n".join(lines) if lines else label


def unique_id(base: Any, used: set[str], fallback_prefix: str) -> str:
    stem = scalar_text(base) or f"{fallback_prefix}_{len(used) + 1}"
    candidate = stem
    suffix = 2
    while candidate in used:
        candidate = f"{stem}__{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def mapping_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        items = []
        for key, raw in value.items():
            if isinstance(raw, dict):
                item = dict(raw)
            else:
                item = {"value": raw}
            item.setdefault("id", str(key))
            item.setdefault("name", item.get("title") or str(key))
            items.append(item)
        return items
    if isinstance(value, list):
        items = []
        for index, raw in enumerate(value, start=1):
            if isinstance(raw, dict):
                item = dict(raw)
            else:
                item = {"value": raw}
            item.setdefault("id", item.get("name") or f"item_{index}")
            item.setdefault("name", item.get("title") or item["id"])
            items.append(item)
        return items
    return []


def first_present(properties: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = scalar_text(properties.get(key))
        if value:
            return value
    return ""


def search_blob(*values: Any) -> str:
    return json.dumps(json_ready(values), ensure_ascii=False, sort_keys=True).lower()


def build_instance_graph(
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    used_node_ids: set[str] = set()
    nodes: list[dict[str, Any]] = []
    node_id_map: dict[str, str] = {}

    for index, raw_node in enumerate(mapping_items(data.get("nodes")), start=1):
        properties = dict(raw_node)
        original_id = scalar_text(properties.get("id")) or scalar_text(
            properties.get("name")
        )
        node_id = unique_id(original_id, used_node_ids, "node")
        node_id_map[original_id or node_id] = node_id
        label = display_name(properties, compact_identifier(node_id))
        group = first_present(properties, NODE_GROUP_KEYS) or "node"
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "displayLabel": wrapped_label(label),
                "group": group,
                "properties": json_ready(properties),
                "searchText": search_blob(node_id, label, group, properties),
            }
        )

    used_edge_ids: set[str] = set()
    edges: list[dict[str, Any]] = []

    for index, raw_edge in enumerate(mapping_items(data.get("edges")), start=1):
        properties = dict(raw_edge)
        endpoint_pair = next(
            (
                (source_key, target_key)
                for source_key, target_key in ENDPOINT_PAIRS
                if properties.get(source_key) is not None
                and properties.get(target_key) is not None
            ),
            None,
        )
        if endpoint_pair is None:
            warnings.append(
                f"Skipped edge {properties.get('id') or index}: no supported endpoint keys found."
            )
            continue

        source_key, target_key = endpoint_pair
        raw_source = scalar_text(properties.get(source_key))
        raw_target = scalar_text(properties.get(target_key))
        source = node_id_map.get(raw_source, raw_source)
        target = node_id_map.get(raw_target, raw_target)

        for endpoint in (source, target):
            if endpoint not in used_node_ids:
                used_node_ids.add(endpoint)
                label = compact_identifier(endpoint)
                generated_properties = {
                    "id": endpoint,
                    "name": label,
                    "generated": True,
                    "note": "Referenced by an edge but not declared in nodes.",
                }
                nodes.append(
                    {
                        "id": endpoint,
                        "label": label,
                        "displayLabel": wrapped_label(label),
                        "group": "referenced node",
                        "properties": generated_properties,
                        "searchText": search_blob(
                            endpoint, label, generated_properties
                        ),
                    }
                )

        edge_id = unique_id(properties.get("id"), used_edge_ids, "edge")
        label = first_present(properties, EDGE_LABEL_KEYS) or "related_to"
        group = label
        edges.append(
            {
                "id": edge_id,
                "from": source,
                "to": target,
                "label": label,
                "group": group,
                "properties": json_ready(properties),
                "searchText": search_blob(edge_id, label, source, target, properties),
            }
        )

    return nodes, edges, warnings


def add_schema_node(
    nodes: list[dict[str, Any]],
    used_node_ids: set[str],
    kind: str,
    properties: dict[str, Any],
) -> str:
    node_id = unique_id(
        properties.get("id") or properties.get("name"), used_node_ids, kind
    )
    label = display_name(properties, compact_identifier(node_id))
    node_properties = dict(properties)
    node_properties.setdefault("id", node_id)
    node_properties.setdefault("linkml_kind", kind)
    nodes.append(
        {
            "id": node_id,
            "label": label,
            "displayLabel": wrapped_label(label),
            "group": kind,
            "properties": json_ready(node_properties),
            "searchText": search_blob(node_id, label, kind, node_properties),
        }
    )
    return node_id


def make_schema_edge(
    used_edge_ids: set[str],
    source: str,
    target: str,
    label: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    properties = dict(properties or {})
    properties.setdefault("predicate", label)
    properties.setdefault("subject", source)
    properties.setdefault("object", target)
    edge_id = unique_id(properties.get("id"), used_edge_ids, "edge")
    return {
        "id": edge_id,
        "from": source,
        "to": target,
        "label": label,
        "group": label,
        "properties": json_ready(properties),
        "searchText": search_blob(edge_id, label, source, target, properties),
    }


def build_schema_graph(
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    used_node_ids: set[str] = set()
    used_edge_ids: set[str] = set()
    known: dict[str, str] = {}

    for kind in ("class", "slot", "enum", "type"):
        top_key = f"{kind}es" if kind == "class" else f"{kind}s"
        if kind == "class":
            top_key = "classes"
        for properties in mapping_items(data.get(top_key)):
            node_id = add_schema_node(nodes, used_node_ids, kind, properties)
            known[scalar_text(properties.get("id")) or node_id] = node_id

    def ensure_node(identifier: str, kind: str = "reference") -> str:
        if identifier in known:
            return known[identifier]
        node_id = unique_id(identifier, used_node_ids, kind)
        known[identifier] = node_id
        properties = {
            "id": identifier,
            "name": compact_identifier(identifier),
            "generated": True,
            "linkml_kind": kind,
            "note": "Referenced by schema relationships but not declared as a top-level element.",
        }
        nodes.append(
            {
                "id": node_id,
                "label": properties["name"],
                "displayLabel": wrapped_label(properties["name"]),
                "group": kind,
                "properties": properties,
                "searchText": search_blob(node_id, properties),
            }
        )
        return node_id

    for class_item in mapping_items(data.get("classes")):
        class_id = known.get(scalar_text(class_item.get("id")))
        if not class_id:
            continue

        parent = scalar_text(class_item.get("is_a"))
        if parent:
            edges.append(
                make_schema_edge(
                    used_edge_ids,
                    class_id,
                    ensure_node(parent, "class"),
                    "is_a",
                    {"predicate": "is_a", "source_field": "is_a"},
                )
            )

        for mixin in class_item.get("mixins") or []:
            if scalar_text(mixin):
                edges.append(
                    make_schema_edge(
                        used_edge_ids,
                        class_id,
                        ensure_node(str(mixin), "mixin"),
                        "mixin",
                        {"predicate": "mixin", "source_field": "mixins"},
                    )
                )

        for slot_name in class_item.get("slots") or []:
            if scalar_text(slot_name):
                edges.append(
                    make_schema_edge(
                        used_edge_ids,
                        class_id,
                        ensure_node(str(slot_name), "slot"),
                        "has_slot",
                        {"predicate": "has_slot", "source_field": "slots"},
                    )
                )

        for attr in mapping_items(class_item.get("attributes")):
            attr_name = scalar_text(attr.get("id")) or scalar_text(attr.get("name"))
            if not attr_name:
                continue
            attr_id = ensure_node(attr_name, "attribute")
            edges.append(
                make_schema_edge(
                    used_edge_ids,
                    class_id,
                    attr_id,
                    "has_attribute",
                    {"predicate": "has_attribute", "attribute": json_ready(attr)},
                )
            )
            attr_range = scalar_text(attr.get("range"))
            if attr_range:
                edges.append(
                    make_schema_edge(
                        used_edge_ids,
                        attr_id,
                        ensure_node(attr_range, "range"),
                        "range",
                        {"predicate": "range", "source_field": "attributes.range"},
                    )
                )

    for slot_item in mapping_items(data.get("slots")):
        slot_id = known.get(scalar_text(slot_item.get("id")))
        if not slot_id:
            continue
        domain = scalar_text(slot_item.get("domain"))
        if domain:
            edges.append(
                make_schema_edge(
                    used_edge_ids,
                    ensure_node(domain, "class"),
                    slot_id,
                    "domain_slot",
                    {"predicate": "domain_slot", "source_field": "domain"},
                )
            )
        slot_range = scalar_text(slot_item.get("range"))
        if slot_range:
            edges.append(
                make_schema_edge(
                    used_edge_ids,
                    slot_id,
                    ensure_node(slot_range, "range"),
                    "range",
                    {"predicate": "range", "source_field": "range"},
                )
            )

    if not nodes:
        warnings.append(
            "No nodes were found in top-level nodes, classes, slots, enums, or types."
        )
    if not edges:
        warnings.append(
            "No edges were found from edge records or schema relationships."
        )

    return nodes, edges, warnings


def extract_graph(
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], str]:
    if "nodes" in data or "edges" in data:
        nodes, edges, warnings = build_instance_graph(data)
        return nodes, edges, warnings, "node_edge"
    nodes, edges, warnings = build_schema_graph(data)
    return nodes, edges, warnings, "linkml_schema"


def graph_title(data: dict[str, Any], source: Path, override: str | None = None) -> str:
    if override:
        return override
    for key in ("title", "name", "graph_id", "id"):
        value = scalar_text(data.get(key))
        if value:
            return value
    docs = data.get("source_documents")
    if isinstance(docs, list) and docs and isinstance(docs[0], dict):
        value = scalar_text(docs[0].get("title"))
        if value:
            return value
    return source.stem


def strip_source_map_comment(text: str) -> str:
    return re.sub(r"\n//# sourceMappingURL=.*", "", text)


def read_pyvis_asset(filename: str) -> str | None:
    try:
        import pyvis
    except ImportError:
        return None

    pyvis_root = Path(pyvis.__file__).resolve().parent
    candidates = (
        pyvis_root / "lib" / f"vis-{VIS_VERSION}" / filename,
        pyvis_root / "templates" / "lib" / f"vis-{VIS_VERSION}" / filename,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return None


def download_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read().decode("utf-8")


def asset_tags(use_cdn: bool) -> str:
    if use_cdn:
        return (
            f'<link rel="stylesheet" href="{VIS_CSS_CDN}">\n'
            f'<script src="{VIS_JS_CDN}"></script>'
        )

    css = read_pyvis_asset("vis-network.css")
    js = read_pyvis_asset("vis-network.min.js")

    if css is None:
        css = download_text(VIS_CSS_CDN)
    if js is None:
        js = download_text(VIS_JS_CDN)

    js = strip_source_map_comment(js).replace("</script", "<\\/script")
    return f"<style>\n{css}\n</style>\n<script>\n{js}\n</script>"


def build_graph_payload(
    data: dict[str, Any],
    source: Path,
    title: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    warnings: list[str],
    graph_kind: str,
) -> dict[str, Any]:
    metadata = {
        key: value
        for key, value in data.items()
        if key not in {"nodes", "edges", "classes", "slots", "enums", "types"}
    }
    node_group_counts = Counter(node["group"] for node in nodes)
    edge_group_counts = Counter(edge["group"] for edge in edges)
    return {
        "title": title,
        "sourceFile": str(source),
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "graphKind": graph_kind,
        "nodes": nodes,
        "edges": edges,
        "nodeGroups": sorted(node_group_counts),
        "edgeGroups": sorted(edge_group_counts),
        "nodeGroupCounts": dict(sorted(node_group_counts.items())),
        "edgeGroupCounts": dict(sorted(edge_group_counts.items())),
        "metadata": json_ready(metadata),
        "warnings": warnings,
    }


CUSTOM_CSS = r"""
:root {
  color-scheme: light dark;
  --bg: #f6f8fb;
  --panel: #ffffff;
  --panel-2: #f8fafc;
  --text: #111827;
  --muted: #64748b;
  --border: #d8dee9;
  --accent: #2563eb;
  --accent-strong: #1d4ed8;
  --shadow: 0 18px 50px rgba(15, 23, 42, 0.12);
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f172a;
    --panel: #172033;
    --panel-2: #111827;
    --text: #e5e7eb;
    --muted: #9ca3af;
    --border: #314057;
    --accent: #60a5fa;
    --accent-strong: #93c5fd;
    --shadow: 0 18px 50px rgba(0, 0, 0, 0.35);
  }
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

button,
input,
select {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 18px 22px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}

.title-block {
  min-width: 0;
}

h1 {
  margin: 0;
  font-size: clamp(20px, 2.3vw, 30px);
  line-height: 1.15;
  letter-spacing: 0;
}

.meta-line,
.status-line {
  color: var(--muted);
  font-size: 13px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-top: 7px;
}

.header-actions,
.toolbar,
.tab-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.toolbar {
  padding: 12px 22px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}

.field {
  display: grid;
  gap: 4px;
  color: var(--muted);
  font-size: 12px;
}

.field input,
.field select {
  min-height: 36px;
  min-width: 190px;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 10px;
}

.field.search-field {
  flex: 1 1 260px;
}

.field.search-field input {
  width: 100%;
}

.btn,
.tab-button,
.directory-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-2);
  color: var(--text);
  cursor: pointer;
}

.btn {
  min-height: 36px;
  padding: 7px 11px;
}

.btn:hover,
.tab-button:hover,
.directory-item:hover {
  border-color: var(--accent);
}

.btn.primary {
  background: var(--accent);
  color: white;
  border-color: var(--accent);
}

.workspace {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(330px, 390px);
  gap: 14px;
  padding: 14px;
}

.graph-panel,
.sidebar {
  min-width: 0;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: var(--shadow);
}

.graph-panel {
  position: relative;
  overflow: hidden;
}

#network {
  height: calc(100vh - 172px);
  min-height: 520px;
}

.graph-status {
  position: absolute;
  left: 12px;
  bottom: 12px;
  max-width: calc(100% - 24px);
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--muted);
  background: color-mix(in srgb, var(--panel) 88%, transparent);
  backdrop-filter: blur(8px);
  font-size: 13px;
}

.sidebar {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
}

.tab-list {
  padding: 10px;
  border-bottom: 1px solid var(--border);
}

.tab-button {
  padding: 7px 10px;
}

.tab-button[aria-selected="true"] {
  background: var(--accent);
  color: white;
  border-color: var(--accent);
}

.tab-panel {
  min-height: 0;
  overflow: auto;
  padding: 14px;
}

.detail-heading {
  margin-bottom: 12px;
}

.eyebrow {
  margin: 0 0 4px;
  color: var(--muted);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.detail-title {
  margin: 0;
  font-size: 19px;
  line-height: 1.2;
}

.detail-subtitle {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}

.summary-item {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px;
  min-width: 0;
}

.summary-label {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 3px;
}

.summary-value {
  display: block;
  font-size: 13px;
  overflow-wrap: anywhere;
}

.property-json,
.metadata-json {
  margin: 0;
  padding: 12px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  line-height: 1.45;
}

.directory-list {
  display: grid;
  gap: 7px;
}

.directory-item {
  width: 100%;
  display: grid;
  gap: 4px;
  padding: 9px 10px;
  text-align: left;
}

.directory-name {
  font-weight: 600;
  line-height: 1.2;
}

.directory-meta {
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.empty-state,
.warning-list {
  color: var(--muted);
  font-size: 13px;
}

.warning-list {
  margin-top: 12px;
  padding-left: 18px;
}

.vis-tooltip {
  white-space: pre-line !important;
  max-width: 360px;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif !important;
}

@media (max-width: 940px) {
  .app-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .workspace {
    grid-template-columns: 1fr;
  }

  #network {
    height: 62vh;
    min-height: 420px;
  }

  .sidebar {
    max-height: none;
  }
}

@media (max-width: 560px) {
  .toolbar,
  .app-header,
  .workspace {
    padding-left: 10px;
    padding-right: 10px;
  }

  .field,
  .field input,
  .field select,
  .btn {
    width: 100%;
  }

  .summary-grid {
    grid-template-columns: 1fr;
  }
}
"""


CUSTOM_JS = r"""
(() => {
  const graph = JSON.parse(document.getElementById("graph-data").textContent);
  document.title = `${graph.title} | LinkML graph`;

  const el = {
    title: document.getElementById("graph-title"),
    meta: document.getElementById("graph-meta"),
    search: document.getElementById("search"),
    nodeGroup: document.getElementById("node-group"),
    edgeGroup: document.getElementById("edge-group"),
    clearFilters: document.getElementById("clear-filters"),
    fit: document.getElementById("fit-graph"),
    physics: document.getElementById("toggle-physics"),
    edgeLabels: document.getElementById("edge-labels"),
    status: document.getElementById("graph-status"),
    network: document.getElementById("network"),
    detailsKind: document.getElementById("details-kind"),
    detailsTitle: document.getElementById("details-title"),
    detailsSubtitle: document.getElementById("details-subtitle"),
    detailsSummary: document.getElementById("details-summary"),
    detailsJson: document.getElementById("details-json"),
    nodeList: document.getElementById("node-list"),
    edgeList: document.getElementById("edge-list"),
    metadataJson: document.getElementById("metadata-json"),
    warnings: document.getElementById("warnings"),
  };

  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const edgeById = new Map(graph.edges.map((edge) => [edge.id, edge]));
  const degree = new Map(graph.nodes.map((node) => [node.id, 0]));
  graph.edges.forEach((edge) => {
    degree.set(edge.from, (degree.get(edge.from) || 0) + 1);
    degree.set(edge.to, (degree.get(edge.to) || 0) + 1);
  });

  const palette = [
    { background: "#dbeafe", border: "#2563eb", highlight: "#bfdbfe" },
    { background: "#dcfce7", border: "#16a34a", highlight: "#bbf7d0" },
    { background: "#fef3c7", border: "#d97706", highlight: "#fde68a" },
    { background: "#fce7f3", border: "#db2777", highlight: "#fbcfe8" },
    { background: "#ede9fe", border: "#7c3aed", highlight: "#ddd6fe" },
    { background: "#ccfbf1", border: "#0f766e", highlight: "#99f6e4" },
    { background: "#fee2e2", border: "#dc2626", highlight: "#fecaca" },
    { background: "#e0f2fe", border: "#0284c7", highlight: "#bae6fd" },
    { background: "#f5d0fe", border: "#c026d3", highlight: "#f0abfc" },
    { background: "#e2e8f0", border: "#475569", highlight: "#cbd5e1" },
  ];

  const edgePalette = [
    "#b45309",
    "#2563eb",
    "#16a34a",
    "#db2777",
    "#7c3aed",
    "#0f766e",
    "#dc2626",
    "#475569",
  ];

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function shortValue(value) {
    if (value === null || value === undefined || value === "") return "";
    if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
    if (typeof value === "object") return `${Object.keys(value).length} field${Object.keys(value).length === 1 ? "" : "s"}`;
    const text = String(value);
    return text.length > 110 ? `${text.slice(0, 107)}...` : text;
  }

  function scalarDetail(value) {
    if (value === null || value === undefined || value === "") return "";
    if (Array.isArray(value)) {
      return value.map((item) => scalarDetail(item)).filter(Boolean).join("; ");
    }
    if (typeof value === "object") {
      return (
        value.entity_term ||
        value.term ||
        value.name ||
        value.id ||
        Object.entries(value)
          .map(([key, itemValue]) => `${key}: ${scalarDetail(itemValue)}`)
          .filter((entry) => !entry.endsWith(": "))
          .join(", ")
      );
    }
    return String(value);
  }

  function firstNodeValue(props, keys) {
    for (const key of keys) {
      const value = scalarDetail(props?.[key]);
      if (value) return value;
    }
    return "";
  }

  function formatAppliedTo(value) {
    if (!value) return "";
    const entries = Array.isArray(value) ? value : [value];
    return entries
      .map((entry) => {
        if (entry && typeof entry === "object" && !Array.isArray(entry)) {
          const type = scalarDetail(entry.entity_type || entry.type);
          const term = scalarDetail(entry.entity_term || entry.term || entry.name || entry.id);
          if (type && term) return `${type}: ${term}`;
          return term || type || scalarDetail(entry);
        }
        return scalarDetail(entry);
      })
      .filter(Boolean)
      .join("; ");
  }

  function nodeDetailRows(item) {
    const props = item.properties || {};
    const entityType = firstNodeValue(props, ["entity_type", "type", "category"]);
    const entityTerm = firstNodeValue(props, ["entity_term", "entity", "term"]);
    const entity = entityTerm && entityType ? `${entityTerm} (${entityType})` : entityTerm || entityType;
    const state = firstNodeValue(props, ["state_or_change_qualifier", "change_direction", "direction", "state"]);
    const attribute = firstNodeValue(props, ["measured_attribute", "attribute"]);
    const appliedTo = formatAppliedTo(props.applied_to);
    return [
      ["id", props.id],
      ["entity", entity],
      ["state/change", state],
      ["attribute", attribute],
      ["applied_to", appliedTo],
    ];
  }

  function option(label, value) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    return opt;
  }

  function fillOptions(select, values, counts, allLabel) {
    select.replaceChildren(option(allLabel, "__all__"));
    values.forEach((value) => {
      const count = counts[value] || 0;
      select.appendChild(option(`${value} (${count})`, value));
    });
  }

  function nodeLabel(id) {
    return nodeById.get(id)?.label || id;
  }

  function edgeEndpoints(edge) {
    return `${nodeLabel(edge.from)} -> ${nodeLabel(edge.to)}`;
  }

  function isAssociational(edge) {
    const text = `${edge.label} ${edge.group} ${edge.properties?.claim_strength || ""}`.toLowerCase();
    return text.includes("associated") || text.includes("correlation") || text.includes("observational");
  }

  function edgeWidth(edge) {
    const confidence = Number(edge.properties?.annotation_confidence);
    if (Number.isFinite(confidence)) return 1.4 + Math.min(Math.max(confidence, 0), 1) * 1.4;
    const numeric = Number(edge.properties?.strength?.quantitative_numeric);
    if (Number.isFinite(numeric)) return 1.4 + Math.min(Math.abs(numeric), 2);
    return 2;
  }

  function tooltipFor(type, item) {
    const props = item.properties || {};
    const rows = type === "node" ? nodeDetailRows(item) : [
      ["id", props.id],
      ["predicate", props.predicate],
      ["claim_strength", props.claim_strength],
      ["annotation_confidence", props.annotation_confidence],
      ["original_sentence", props.original_sentence],
    ];
    const textRows = rows
      .filter(([, value]) => value !== undefined && value !== null && value !== "")
      .map(([key, value]) => `${key}: ${shortValue(value)}`);
    return [item.label, ...textRows].join("\n");
  }

  function groupOptions() {
    const groups = {};
    graph.nodeGroups.forEach((group, index) => {
      const colors = palette[index % palette.length];
      groups[group] = {
        shape: "box",
        color: {
          background: colors.background,
          border: colors.border,
          highlight: { background: colors.highlight, border: colors.border },
          hover: { background: colors.highlight, border: colors.border },
        },
        borderWidth: 1.5,
        font: { color: "#0f172a" },
      };
    });
    return groups;
  }

  function edgeColor(edge) {
    const index = Math.max(0, graph.edgeGroups.indexOf(edge.group));
    const color = edgePalette[index % edgePalette.length];
    return { color, highlight: color, hover: color, opacity: 0.84 };
  }

  el.title.textContent = graph.title;
  el.meta.textContent = [
    `${graph.nodes.length} nodes`,
    `${graph.edges.length} edges`,
    graph.sourceFile,
  ].join(" | ");
  el.metadataJson.textContent = JSON.stringify(
    {
      source_file: graph.sourceFile,
      generated_at: graph.generatedAt,
      graph_kind: graph.graphKind,
      metadata: graph.metadata,
    },
    null,
    2
  );

  if (graph.warnings.length) {
    const list = document.createElement("ul");
    list.className = "warning-list";
    graph.warnings.forEach((warning) => {
      const item = document.createElement("li");
      item.textContent = warning;
      list.appendChild(item);
    });
    el.warnings.appendChild(list);
  }

  fillOptions(el.nodeGroup, graph.nodeGroups, graph.nodeGroupCounts, "All node groups");
  fillOptions(el.edgeGroup, graph.edgeGroups, graph.edgeGroupCounts, "All edge types");

  if (!window.vis || !vis.Network || !vis.DataSet) {
    el.network.innerHTML = '<div class="empty-state" style="padding: 16px;">vis-network did not load. Rebuild without --cdn for an offline file, or open this file with internet access.</div>';
    return;
  }

  const visNodes = new vis.DataSet(
    graph.nodes.map((node) => ({
      id: node.id,
      label: node.displayLabel || node.label,
      group: node.group || "node",
      title: tooltipFor("node", node),
      margin: { top: 8, right: 10, bottom: 8, left: 10 },
      widthConstraint: { maximum: 190 },
      mass: 1 + Math.min((degree.get(node.id) || 0) / 4, 2),
    }))
  );

  const visEdges = new vis.DataSet(
    graph.edges.map((edge) => ({
      id: edge.id,
      from: edge.from,
      to: edge.to,
      label: edge.label,
      title: tooltipFor("edge", edge),
      arrows: { to: { enabled: true, scaleFactor: 0.75 } },
      color: edgeColor(edge),
      dashes: isAssociational(edge),
      width: edgeWidth(edge),
      smooth: { type: "dynamic", roundness: 0.32 },
      font: {
        align: "middle",
        size: 12,
        color: cssVar("--text"),
        strokeWidth: 4,
        strokeColor: cssVar("--panel"),
      },
    }))
  );

  const network = new vis.Network(
    el.network,
    { nodes: visNodes, edges: visEdges },
    {
      groups: groupOptions(),
      layout: { improvedLayout: true },
      nodes: {
        shape: "box",
        borderWidth: 1.5,
        shadow: { enabled: true, color: "rgba(15, 23, 42, 0.14)", size: 8, x: 0, y: 3 },
        font: {
          face: "Inter, Segoe UI, sans-serif",
          size: 14,
          color: "#0f172a",
          multi: "html",
        },
      },
      edges: {
        arrows: "to",
        selectionWidth: 2,
        hoverWidth: 1.5,
      },
      physics: {
        solver: "forceAtlas2Based",
        stabilization: { enabled: true, iterations: 220, updateInterval: 25 },
        forceAtlas2Based: {
          gravitationalConstant: -74,
          centralGravity: 0.012,
          springLength: 155,
          springConstant: 0.08,
          damping: 0.45,
          avoidOverlap: 0.35,
        },
      },
      interaction: {
        hover: true,
        tooltipDelay: 120,
        navigationButtons: true,
        keyboard: true,
        multiselect: false,
      },
    }
  );

  let physicsRunning = true;
  let visibleNodeIds = new Set(graph.nodes.map((node) => node.id));
  let visibleEdgeIds = new Set(graph.edges.map((edge) => edge.id));

  function setPhysics(running) {
    physicsRunning = running;
    network.setOptions({ physics: running });
    el.physics.textContent = running ? "Pause physics" : "Resume physics";
  }

  network.once("stabilizationIterationsDone", () => {
    setPhysics(false);
    network.fit({ animation: { duration: 450, easingFunction: "easeInOutQuad" } });
  });

  function normalized(text) {
    return String(text ?? "").toLowerCase();
  }

  const nodeSearch = new Map(graph.nodes.map((node) => [node.id, normalized(node.searchText)]));
  const edgeSearch = new Map(graph.edges.map((edge) => [edge.id, normalized(edge.searchText)]));

  function nodeMatchesGroup(node, selectedGroup) {
    return selectedGroup === "__all__" || node.group === selectedGroup;
  }

  function edgeMatchesGroup(edge, selectedGroup) {
    return selectedGroup === "__all__" || edge.group === selectedGroup;
  }

  function edgeTouchesNodeGroup(edge, selectedGroup) {
    if (selectedGroup === "__all__") return true;
    return nodeById.get(edge.from)?.group === selectedGroup || nodeById.get(edge.to)?.group === selectedGroup;
  }

  function applyFilters(options = {}) {
    const query = normalized(el.search.value.trim());
    const selectedNodeGroup = el.nodeGroup.value;
    const selectedEdgeGroup = el.edgeGroup.value;
    const nextNodes = new Set();
    const nextEdges = new Set();

    graph.nodes.forEach((node) => {
      if (!nodeMatchesGroup(node, selectedNodeGroup)) return;
      if (!query || nodeSearch.get(node.id).includes(query)) {
        nextNodes.add(node.id);
      }
    });

    graph.edges.forEach((edge) => {
      if (!edgeMatchesGroup(edge, selectedEdgeGroup)) return;
      if (!edgeTouchesNodeGroup(edge, selectedNodeGroup)) return;

      const endpointSearch = `${nodeSearch.get(edge.from) || ""} ${nodeSearch.get(edge.to) || ""}`;
      const matchesQuery = !query || edgeSearch.get(edge.id).includes(query) || endpointSearch.includes(query);
      const touchesVisibleNode = nextNodes.has(edge.from) || nextNodes.has(edge.to);
      if (matchesQuery || (query && touchesVisibleNode)) {
        nextEdges.add(edge.id);
        nextNodes.add(edge.from);
        nextNodes.add(edge.to);
      }
    });

    visibleNodeIds = nextNodes;
    visibleEdgeIds = nextEdges;

    visNodes.update(
      graph.nodes.map((node) => ({
        id: node.id,
        hidden: !visibleNodeIds.has(node.id),
      }))
    );
    visEdges.update(
      graph.edges.map((edge) => ({
        id: edge.id,
        hidden: !visibleEdgeIds.has(edge.id),
        label: el.edgeLabels.checked ? edge.label : "",
      }))
    );

    el.status.textContent = `${visibleNodeIds.size}/${graph.nodes.length} nodes | ${visibleEdgeIds.size}/${graph.edges.length} edges visible`;
    renderDirectories();
    if (options.fit) {
      network.fit({ animation: { duration: 300, easingFunction: "easeInOutQuad" } });
    }
  }

  function setActiveTab(tabName) {
    document.querySelectorAll(".tab-button").forEach((button) => {
      const selected = button.dataset.tab === tabName;
      button.setAttribute("aria-selected", selected ? "true" : "false");
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.hidden = panel.dataset.panel !== tabName;
    });
  }

  function renderSummaryRows(rows) {
    el.detailsSummary.replaceChildren();
    rows.filter((row) => row.value !== undefined && row.value !== null && row.value !== "").forEach((row) => {
      const item = document.createElement("div");
      item.className = "summary-item";
      const label = document.createElement("span");
      label.className = "summary-label";
      label.textContent = row.label;
      const value = document.createElement("span");
      value.className = "summary-value";
      value.textContent = shortValue(row.value);
      item.append(label, value);
      el.detailsSummary.appendChild(item);
    });
  }

  function showOverview() {
    el.detailsKind.textContent = "Graph";
    el.detailsTitle.textContent = graph.title;
    el.detailsSubtitle.textContent = graph.sourceFile;
    renderSummaryRows([
      { label: "Nodes", value: graph.nodes.length },
      { label: "Edges", value: graph.edges.length },
      { label: "Node groups", value: graph.nodeGroups.length },
      { label: "Edge types", value: graph.edgeGroups.length },
    ]);
    el.detailsJson.textContent = JSON.stringify(
      {
        source_file: graph.sourceFile,
        generated_at: graph.generatedAt,
        graph_kind: graph.graphKind,
        node_group_counts: graph.nodeGroupCounts,
        edge_type_counts: graph.edgeGroupCounts,
        metadata: graph.metadata,
        warnings: graph.warnings,
      },
      null,
      2
    );
  }

  function showNode(nodeId, focus = false) {
    const node = nodeById.get(nodeId);
    if (!node) return;
    el.detailsKind.textContent = "Node";
    el.detailsTitle.textContent = node.label;
    el.detailsSubtitle.textContent = node.id;
    renderSummaryRows([
      { label: "Group", value: node.group },
      { label: "Degree", value: degree.get(node.id) || 0 },
      { label: "Entity", value: node.properties?.entity_term },
      { label: "State", value: node.properties?.state_or_change_qualifier },
      { label: "Attribute", value: node.properties?.measured_attribute },
      { label: "Applied to", value: formatAppliedTo(node.properties?.applied_to) },
    ]);
    el.detailsJson.textContent = JSON.stringify(node.properties, null, 2);
    setActiveTab("details");
    if (focus) {
      network.selectNodes([node.id]);
      network.focus(node.id, { scale: 1.15, animation: { duration: 350, easingFunction: "easeInOutQuad" } });
    }
  }

  function showEdge(edgeId, focus = false) {
    const edge = edgeById.get(edgeId);
    if (!edge) return;
    el.detailsKind.textContent = "Edge";
    el.detailsTitle.textContent = edge.label;
    el.detailsSubtitle.textContent = edgeEndpoints(edge);
    renderSummaryRows([
      { label: "From", value: nodeLabel(edge.from) },
      { label: "To", value: nodeLabel(edge.to) },
      { label: "Type", value: edge.group },
      { label: "Confidence", value: edge.properties?.annotation_confidence },
    ]);
    el.detailsJson.textContent = JSON.stringify(edge.properties, null, 2);
    setActiveTab("details");
    if (focus) {
      network.selectEdges([edge.id]);
      const selectedNodes = [edge.from, edge.to].filter((nodeId) => visibleNodeIds.has(nodeId));
      if (selectedNodes.length) {
        network.fit({ nodes: selectedNodes, animation: { duration: 350, easingFunction: "easeInOutQuad" } });
      }
    }
  }

  function directoryButton(item, type) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "directory-item";
    const name = document.createElement("span");
    name.className = "directory-name";
    name.textContent = item.label;
    const meta = document.createElement("span");
    meta.className = "directory-meta";
    meta.textContent = type === "node" ? `${item.group} | ${item.id}` : `${edgeEndpoints(item)} | ${item.id}`;
    button.append(name, meta);
    button.addEventListener("click", () => {
      if (type === "node") showNode(item.id, true);
      else showEdge(item.id, true);
    });
    return button;
  }

  function renderDirectories() {
    el.nodeList.replaceChildren();
    el.edgeList.replaceChildren();

    const visibleNodes = graph.nodes.filter((node) => visibleNodeIds.has(node.id));
    const visibleEdges = graph.edges.filter((edge) => visibleEdgeIds.has(edge.id));

    if (!visibleNodes.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No visible nodes.";
      el.nodeList.appendChild(empty);
    } else {
      visibleNodes
        .slice()
        .sort((a, b) => a.label.localeCompare(b.label))
        .forEach((node) => el.nodeList.appendChild(directoryButton(node, "node")));
    }

    if (!visibleEdges.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No visible edges.";
      el.edgeList.appendChild(empty);
    } else {
      visibleEdges
        .slice()
        .sort((a, b) => a.label.localeCompare(b.label) || edgeEndpoints(a).localeCompare(edgeEndpoints(b)))
        .forEach((edge) => el.edgeList.appendChild(directoryButton(edge, "edge")));
    }
  }

  network.on("selectNode", (params) => {
    if (params.nodes.length) showNode(params.nodes[0], false);
  });

  network.on("selectEdge", (params) => {
    if (params.edges.length && !params.nodes.length) showEdge(params.edges[0], false);
  });

  network.on("deselectNode", (params) => {
    if (!params.nodes.length && !params.edges.length) showOverview();
  });

  network.on("deselectEdge", (params) => {
    if (!params.nodes.length && !params.edges.length) showOverview();
  });

  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => setActiveTab(button.dataset.tab));
  });

  [el.search, el.nodeGroup, el.edgeGroup, el.edgeLabels].forEach((control) => {
    control.addEventListener("input", () => applyFilters());
    control.addEventListener("change", () => applyFilters());
  });

  el.clearFilters.addEventListener("click", () => {
    el.search.value = "";
    el.nodeGroup.value = "__all__";
    el.edgeGroup.value = "__all__";
    applyFilters({ fit: true });
  });

  el.fit.addEventListener("click", () => {
    network.fit({ animation: { duration: 400, easingFunction: "easeInOutQuad" } });
  });

  el.physics.addEventListener("click", () => {
    setPhysics(!physicsRunning);
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    visEdges.update(
      graph.edges.map((edge) => ({
        id: edge.id,
        font: {
          color: cssVar("--text"),
          strokeColor: cssVar("--panel"),
        },
      }))
    );
  });

  showOverview();
  applyFilters();
})();
"""


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LinkML graph</title>
  __ASSET_TAGS__
  <style>
__CUSTOM_CSS__
  </style>
</head>
<body>
  <div class="app-shell">
    <header class="app-header">
      <div class="title-block">
        <h1 id="graph-title">LinkML graph</h1>
        <div class="meta-line" id="graph-meta"></div>
      </div>
      <div class="header-actions">
        <button class="btn" type="button" id="fit-graph">Fit</button>
        <button class="btn" type="button" id="toggle-physics">Pause physics</button>
        <label class="btn" for="edge-labels">
          <input id="edge-labels" type="checkbox" checked>
          Edge labels
        </label>
      </div>
    </header>

    <section class="toolbar" aria-label="Graph filters">
      <label class="field search-field" for="search">
        Search
        <input id="search" type="search" placeholder="Node, edge, property, evidence">
      </label>
      <label class="field" for="node-group">
        Node group
        <select id="node-group"></select>
      </label>
      <label class="field" for="edge-group">
        Edge type
        <select id="edge-group"></select>
      </label>
      <button class="btn" type="button" id="clear-filters">Clear</button>
    </section>

    <main class="workspace">
      <section class="graph-panel" aria-label="Graph canvas">
        <div id="network"></div>
        <div class="graph-status" id="graph-status" aria-live="polite"></div>
      </section>

      <aside class="sidebar" aria-label="Graph inspector">
        <nav class="tab-list" aria-label="Inspector tabs">
          <button class="tab-button" type="button" data-tab="details" aria-selected="true">Details</button>
          <button class="tab-button" type="button" data-tab="nodes" aria-selected="false">Nodes</button>
          <button class="tab-button" type="button" data-tab="edges" aria-selected="false">Edges</button>
          <button class="tab-button" type="button" data-tab="metadata" aria-selected="false">Metadata</button>
        </nav>

        <section class="tab-panel" data-panel="details">
          <div class="detail-heading">
            <p class="eyebrow" id="details-kind">Graph</p>
            <h2 class="detail-title" id="details-title">LinkML graph</h2>
            <p class="detail-subtitle" id="details-subtitle"></p>
          </div>
          <div class="summary-grid" id="details-summary"></div>
          <pre class="property-json" id="details-json"></pre>
        </section>

        <section class="tab-panel" data-panel="nodes" hidden>
          <div class="directory-list" id="node-list"></div>
        </section>

        <section class="tab-panel" data-panel="edges" hidden>
          <div class="directory-list" id="edge-list"></div>
        </section>

        <section class="tab-panel" data-panel="metadata" hidden>
          <pre class="metadata-json" id="metadata-json"></pre>
          <div id="warnings"></div>
        </section>
      </aside>
    </main>
  </div>

  <script id="graph-data" type="application/json">
__GRAPH_JSON__
  </script>
  <script>
__CUSTOM_JS__
  </script>
</body>
</html>
"""


def render_html(payload: dict[str, Any], use_cdn: bool) -> str:
    return (
        HTML_TEMPLATE.replace("__ASSET_TAGS__", asset_tags(use_cdn))
        .replace("__CUSTOM_CSS__", CUSTOM_CSS)
        .replace("__GRAPH_JSON__", safe_json_for_script(payload))
        .replace("__CUSTOM_JS__", CUSTOM_JS)
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a standalone HTML graph viewer from a LinkML-style YAML file."
    )
    parser.add_argument("yaml_file", type=Path, help="Input LinkML-style YAML file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output HTML path. Defaults to the input filename with .html.",
    )
    parser.add_argument(
        "--title",
        help="Override the title shown in the generated viewer.",
    )
    parser.add_argument(
        "--cdn",
        action="store_true",
        help="Reference vis-network from a CDN instead of inlining it.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated HTML in the default browser.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    yaml_path = args.yaml_file.expanduser().resolve()
    if not yaml_path.exists():
        raise SystemExit(f"Input YAML file not found: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise SystemExit("Expected the YAML root to be a mapping/object.")

    output_path = (args.output or yaml_path.with_suffix(".html")).expanduser().resolve()
    title = graph_title(data, yaml_path, args.title)
    nodes, edges, warnings, graph_kind = extract_graph(data)
    if not nodes:
        raise SystemExit("No graph nodes could be extracted from the YAML file.")

    payload = build_graph_payload(
        data=data,
        source=yaml_path,
        title=title,
        nodes=nodes,
        edges=edges,
        warnings=warnings,
        graph_kind=graph_kind,
    )
    html = render_html(payload, args.cdn)
    output_path.write_text(html, encoding="utf-8")

    print(f"Wrote {output_path}")
    print(f"Nodes: {len(nodes)}")
    print(f"Edges: {len(edges)}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    if args.open:
        webbrowser.open(output_path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
