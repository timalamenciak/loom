"""Detect config/loom_ui.yaml entries that no longer resolve against the
active schema.

LoomSchemaView.form_spec() silently drops any ui_layers slot name the schema
doesn't define (see schema_engine.py) — a CAMO rename/removal otherwise just
makes a field vanish from the annotation form with no signal. This module
surfaces that drift instead.
"""

from __future__ import annotations


def check_ui_config_drift(
    schema_view,
    ui_config: dict,
    *,
    edge_class: str = "CausalEdge",
) -> list[str]:
    """Return a warning string for each loom_ui.yaml slot reference the
    active schema no longer defines. Empty list means no drift detected.

    `layers` lays out the CausalEdge form specifically, so those entries are
    checked against CausalEdge's own slots. `ontology_routing` and
    `widget_overrides` apply across whichever class's form happens to render
    that slot (e.g. entity_term is a CausalNode slot), so those are checked
    against the union of slots across every class in the schema.
    """
    edge_slots = set(schema_view.slot_names(edge_class))
    any_class_slots: set[str] = set(edge_slots)
    for class_name in schema_view.class_names():
        any_class_slots.update(schema_view.slot_names(class_name))

    warnings: list[str] = []

    for layer in ui_config.get("layers") or []:
        for slot_name in layer.get("slots") or []:
            if slot_name not in edge_slots:
                warnings.append(
                    f"layers: {layer.get('id')!r} references slot {slot_name!r}, "
                    f"which is not defined on {edge_class} in the active schema."
                )

    for slot_name in ui_config.get("ontology_routing") or {}:
        if slot_name not in any_class_slots:
            warnings.append(
                f"ontology_routing references slot {slot_name!r}, which is not "
                "defined on any class in the active schema."
            )

    for slot_name in ui_config.get("widget_overrides") or {}:
        if slot_name not in any_class_slots:
            warnings.append(
                f"widget_overrides references slot {slot_name!r}, which is not "
                "defined on any class in the active schema."
            )

    return warnings
