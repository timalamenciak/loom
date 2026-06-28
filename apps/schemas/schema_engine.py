"""
Schema engine: wraps linkml-runtime SchemaView and builds form specs.

A form spec is a list of layer dicts, each containing a list of slot specs:
  [
    {
      "id": "layer1",
      "label": "Layer 1: Claim & Predicate",
      "collapsed_by_default": False,
      "slots": [
        {
          "name": "claim_strength",
          "label": "Claim Strength",
          "widget": "select",   # text|number|checkbox|select|ontology_autocomplete|fieldset|node_picker
          "required": False,
          "multivalued": False,
          "description": "...",
          "ifabsent": "not_addressed",
          "ontology_prefixes": [],
          "choices": [{"value": "tendency", "label": "Tendency", "description": "...", ...}],
          "nested_spec": [...],  # only for widget=fieldset
        },
        ...
      ],
    },
    ...
  ]
"""

import threading

from linkml_runtime.utils.schemaview import SchemaView

_cache: dict[int, "LoomSchemaView"] = {}
_lock = threading.Lock()

# Primitive range → widget type
_PRIMITIVE_WIDGET = {
    "string": "text",
    "str": "text",
    "integer": "number",
    "int": "number",
    "float": "number",
    "double": "number",
    "boolean": "checkbox",
    "bool": "checkbox",
    "date": "date",
    "datetime": "datetime",
    "uri": "text",
    "anyuri": "text",
    "uriorcurie": "ontology_autocomplete",
    "curie": "ontology_autocomplete",
}


def get_schema_view(schema_version) -> "LoomSchemaView":
    """Return a cached LoomSchemaView for *schema_version*."""
    with _lock:
        if schema_version.pk not in _cache:
            _cache[schema_version.pk] = LoomSchemaView(schema_version)
        return _cache[schema_version.pk]


def invalidate_cache(schema_version_pk: int | None = None):
    """Clear one or all cached views (call after load_schema)."""
    with _lock:
        if schema_version_pk is None:
            _cache.clear()
        else:
            _cache.pop(schema_version_pk, None)


class LoomSchemaView:
    def __init__(self, schema_version):
        self._sv = SchemaView(schema_version.linkml_yaml)
        self.version = schema_version.version

    # ── public ──────────────────────────────────────────────────────────────

    def class_names(self) -> list[str]:
        return list(self._sv.all_classes().keys())

    def enum_names(self) -> list[str]:
        return list(self._sv.all_enums().keys())

    def form_spec(
        self,
        class_name: str,
        ui_layers: list[dict] | None = None,
        ontology_routing: dict | None = None,
        widget_overrides: dict | None = None,
    ) -> list[dict]:
        """
        Build a layered form spec for *class_name*.
        *ui_layers* is the layers list from loom_ui.yaml.
        *ontology_routing* is the ontology_routing dict from loom_ui.yaml.
        """
        if ontology_routing is None:
            ontology_routing = {}
        if widget_overrides is None:
            widget_overrides = {}

        slot_names = self._all_slot_names(class_name)
        slot_specs = {
            name: self._slot_spec(name, class_name, ontology_routing, widget_overrides)
            for name in slot_names
        }

        if not ui_layers:
            return [
                {
                    "id": "all",
                    "label": "",
                    "collapsed_by_default": False,
                    "slots": list(slot_specs.values()),
                }
            ]

        result = []
        assigned: set[str] = set()
        for layer in ui_layers:
            layer_slots = [
                slot_specs[sn] for sn in layer.get("slots", []) if sn in slot_specs
            ]
            if layer_slots:
                result.append(
                    {
                        "id": layer["id"],
                        "label": layer["label"],
                        "collapsed_by_default": layer.get(
                            "collapsed_by_default", False
                        ),
                        "slots": layer_slots,
                    }
                )
            assigned.update(layer.get("slots", []))

        # Remainder (slots not listed in any layer)
        remainder = [s for k, s in slot_specs.items() if k not in assigned]
        if remainder:
            result.append(
                {
                    "id": "other",
                    "label": "Other",
                    "collapsed_by_default": True,
                    "slots": remainder,
                }
            )

        return result

    def bind_form_data(
        self,
        class_name: str,
        form_data,
        *,
        excluded_slots: set[str] | frozenset[str] | None = None,
    ):
        """Bind request data using this graph-pinned schema's induced slots."""
        from .input_binding import bind_form_data

        return bind_form_data(
            self._sv,
            class_name,
            form_data,
            excluded_slots=excluded_slots,
        )

    # ── private ─────────────────────────────────────────────────────────────

    def _all_slot_names(self, class_name: str) -> list[str]:
        """Return all induced fields in schema declaration order.

        LinkML permits fields to be declared through either a class ``slots``
        list or inline class ``attributes``.  ``class_induced_slots`` resolves
        both forms, including inherited fields and slot usage refinements.
        """
        if not self._sv.get_class(class_name):
            return []
        return [slot.name for slot in self._sv.class_induced_slots(class_name)]

    def _slot_spec(
        self,
        slot_name: str,
        class_name: str,
        ontology_routing: dict,
        widget_overrides: dict,
    ) -> dict:
        slot = self._sv.induced_slot(slot_name, class_name)
        slot_range = (slot.range or "string").lower()

        # Widget classification
        if slot_name in widget_overrides:
            widget = widget_overrides[slot_name]
        elif slot_name in ("subject", "object") and slot_range == "causalnode":
            widget = "node_picker"
        elif slot_range in _PRIMITIVE_WIDGET:
            widget = _PRIMITIVE_WIDGET[slot_range]
        elif self._sv.get_enum(slot.range or ""):
            widget = "select"
        elif self._sv.get_class(slot.range or ""):
            widget = "fieldset"
        else:
            widget = "text"

        routing = ontology_routing.get(slot_name, [])
        if isinstance(routing, list):
            ontology_prefixes: list[str] = routing
            wikidata_live: dict | None = None
        else:
            ontology_prefixes = routing.get("prefixes", [])
            wikidata_live = routing.get("wikidata_live") or None

        spec: dict = {
            "name": slot_name,
            "label": (slot.title or slot_name).replace("_", " ").title(),
            "widget": widget,
            "required": bool(slot.required),
            "multivalued": bool(slot.multivalued),
            "description": slot.description or "",
            "ifabsent": slot.ifabsent,
            "ontology_prefixes": ontology_prefixes,
            "wikidata_live": wikidata_live,
            "minimum_value": slot.minimum_value,
            "maximum_value": slot.maximum_value,
            "has_minimum_value": slot.minimum_value is not None,
            "has_maximum_value": slot.maximum_value is not None,
            "minimum_cardinality": getattr(slot, "minimum_cardinality", None),
            "maximum_cardinality": getattr(slot, "maximum_cardinality", None),
            "pattern": slot.pattern or "",
        }

        if widget == "select":
            spec["choices"] = self._enum_choices(slot.range)

        if widget == "fieldset":
            is_inlined = getattr(slot, "inlined", False) or getattr(
                slot, "inlined_as_list", False
            )
            if is_inlined and slot.range:
                spec["nested_spec"] = self.form_spec(
                    slot.range,
                    ui_layers=None,
                    ontology_routing=ontology_routing,
                    widget_overrides=widget_overrides,
                )

        return spec

    def _enum_choices(self, enum_name: str) -> list[dict]:
        enum_def = self._sv.get_enum(enum_name)
        if not enum_def:
            return []
        choices = []
        for pv_name, pv in (enum_def.permissible_values or {}).items():
            ann = pv.annotations or {}
            choices.append(
                {
                    "value": pv_name,
                    "label": pv_name.replace("_", " ").title(),
                    "description": pv.description or "",
                    "linguistic_cues": _ann_value(ann, "linguistic_cues"),
                    "exemplars": _ann_value(ann, "exemplars"),
                }
            )
        return choices


def _ann_value(annotations: dict, key: str) -> str:
    """Extract annotation value safely from linkml Annotation objects or plain strings."""
    if not annotations:
        return ""
    v = annotations.get(key)
    if v is None:
        return ""
    if hasattr(v, "value"):
        return v.value or ""
    return str(v)
