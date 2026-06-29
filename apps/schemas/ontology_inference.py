from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml

from apps.ontology.loaders import ontology_entries

_MAPPING_KEYS = {
    "meaning",
    "exact_mappings",
    "close_mappings",
    "related_mappings",
    "broad_mappings",
    "narrow_mappings",
    "id_prefixes",
}
_UI_CONFIG = Path(__file__).resolve().parents[2] / "config" / "loom_ui.yaml"


def _curie_prefix(value) -> str | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    prefix = value.split(":", 1)[0]
    return prefix if prefix and "/" not in prefix else None


def _walk(value, evidence: dict[str, set[str]]):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _MAPPING_KEYS:
                values = child if isinstance(child, list) else [child]
                for item in values:
                    prefix = _curie_prefix(item)
                    if prefix:
                        evidence[prefix.lower()].add(key)
            _walk(child, evidence)
    elif isinstance(value, list):
        for child in value:
            _walk(child, evidence)


def infer_ontologies(schema_version) -> dict:
    """Return matched registry entries and unresolved prefixes with evidence."""
    document = yaml.safe_load(schema_version.linkml_yaml) or {}
    registry = ontology_entries()
    aliases = {}
    for entry in registry:
        aliases[entry["name"].lower()] = entry
        aliases[entry["prefix"].lower()] = entry

    evidence: dict[str, set[str]] = defaultdict(set)
    declared_external = set()
    for prefix, namespace in (document.get("prefixes") or {}).items():
        evidence[prefix.lower()].add("declared namespace")
        namespace_text = str(namespace)
        if "purl.obolibrary.org/obo" in namespace_text:
            declared_external.add(prefix.lower())
    _walk(document, evidence)

    try:
        ui = yaml.safe_load(_UI_CONFIG.read_text(encoding="utf-8")) or {}
        for routing in (ui.get("ontology_routing") or {}).values():
            if isinstance(routing, dict):
                prefixes = routing.get("prefixes") or []
            else:
                prefixes = routing or []
            for prefix in prefixes:
                evidence[str(prefix).lower()].add("UI ontology routing")
    except FileNotFoundError:
        pass

    matched = {}
    unresolved = []
    for alias, reasons in evidence.items():
        entry = aliases.get(alias)
        if entry:
            matched[entry["name"]] = {
                **entry,
                "reasons": sorted(
                    set(matched.get(entry["name"], {}).get("reasons", [])) | reasons
                ),
            }
        elif reasons - {"declared namespace"} or alias in declared_external:
            unresolved.append({"prefix": alias, "reasons": sorted(reasons)})

    return {
        "matched": sorted(matched.values(), key=lambda item: item["name"]),
        "unresolved": sorted(unresolved, key=lambda item: item["prefix"]),
    }
