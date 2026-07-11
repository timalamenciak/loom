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
          "widget": "select",   # text|number|checkbox|select|ontology_autocomplete|fieldset|node_picker|coordinate_list|applied_to_list|source_span_picker
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

_cache: dict[tuple[int, int], tuple[str, "LoomSchemaView"]] = {}
_lock = threading.Lock()

# Primitive range → widget type
# Enums with more than this many choices get a client-side filterable
# autocomplete widget instead of a plain <select> dropdown.
_LARGE_ENUM_THRESHOLD = 20

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

# Every widget type the annotation form renderer (templates/annotation/
# partials/form_field.html) knows how to draw, keyed by the string that
# appears in a slot spec's "widget" field. This is the canonical list for
# any UI that lets an admin pick/override a slot's widget (see
# apps.schemas.views.FormBuilderView).
WIDGET_MAP = {
    "text": "Text",
    "textarea": "Textarea",
    "number": "Number",
    "checkbox": "Checkbox",
    "date": "Date",
    "datetime": "Date & time",
    "select": "Select (dropdown)",
    "enum_autocomplete": "Enum autocomplete (large enum)",
    "ontology_autocomplete": "Ontology autocomplete",
    "fieldset": "Fieldset (nested class)",
    "node_picker": "Node picker",
    "coordinate_list": "Coordinate list",
    "applied_to_list": "Applied-to list",
    "source_span_picker": "Source span picker",
}


def get_schema_view(schema_version, project=None) -> "LoomSchemaView":
    """Return a cached LoomSchemaView for *schema_version*, bound to *project*.

    Cached per (schema_version.pk, project.pk or 0) — a project-bound view
    resolves its UI config (layers, ontology routing, hidden slots, ...) from
    that project's SchemaUIConfig, so views for different projects must not
    share a cache entry.
    """
    with _lock:
        digest = schema_version.sha256
        key = (schema_version.pk, project.pk if project is not None else 0)
        cached = _cache.get(key)
        if cached is None or cached[0] != digest:
            _cache[key] = (digest, LoomSchemaView(schema_version, project=project))
        return _cache[key][1]


def invalidate_cache(schema_version_pk: int | None = None):
    """Clear one or all cached views (call after load_schema)."""
    with _lock:
        if schema_version_pk is None:
            _cache.clear()
        else:
            for key in [k for k in _cache if k[0] == schema_version_pk]:
                _cache.pop(key, None)


class LoomSchemaView:
    def __init__(self, schema_version, project=None):
        self._sv = SchemaView(schema_version.linkml_yaml)
        self._schema_version = schema_version
        self._project = project
        self.version = schema_version.version

    # ── public ──────────────────────────────────────────────────────────────

    def class_names(self) -> list[str]:
        return list(self._sv.all_classes().keys())

    def enum_names(self) -> list[str]:
        return list(self._sv.all_enums().keys())

    def slot_names(self, class_name: str) -> list[str]:
        """All induced field names for *class_name* in schema declaration order."""
        return self._all_slot_names(class_name)

    def all_slots(self) -> list[str]:
        """Every slot name in the schema, across all classes (schema-wide,
        not scoped to one class) — the flat namespace loom_ui.yaml-shaped
        UI config (layers, widget_overrides, ...) references slot names in.
        """
        return list(self._sv.all_slots().keys())

    def form_spec(
        self,
        class_name: str,
        ui_layers: list[dict] | None = None,
        ontology_routing: dict | None = None,
        widget_overrides: dict | None = None,
        globally_hidden_slots: list[str] | None = None,
        slot_help_texts: dict | None = None,
        geonames_autofill: dict | None = None,
        coordinate_list_fields: dict | None = None,
    ) -> list[dict]:
        """
        Build a layered form spec for *class_name*.
        *ui_layers* is the layers list from loom_ui.yaml.
        *ontology_routing* is the ontology_routing dict from loom_ui.yaml.
        *globally_hidden_slots* are excluded before layer assignment.
        *slot_help_texts* maps slot name → placeholder/hint string shown in the form.
        *geonames_autofill* is the geonames_autofill dict from loom_ui.yaml: maps a
        `coordinate_list`-widget slot name to the sibling country/state slot names
        it should populate (see loom_ui.yaml for the shape).
        *coordinate_list_fields* maps a `coordinate_list`-widget slot name to
        additional nested range-class slots the widget should collect per entry.

        If this view is project-bound (see __init__) and the caller left all
        of ui_layers/ontology_routing/widget_overrides/globally_hidden_slots/
        slot_help_texts unset, they are resolved from
        SchemaUIConfig.for_schema_version() instead of defaulting to empty —
        this is what lets a project override layers/hidden slots/etc. without
        every caller having to look up and thread that config by hand. A
        caller that passes any of these explicitly opts out of this lookup
        entirely (used for recursive nested_spec calls, and by callers that
        already resolved config themselves).
        """
        if (
            self._project is not None
            and ui_layers is None
            and ontology_routing is None
            and widget_overrides is None
            and globally_hidden_slots is None
            and slot_help_texts is None
        ):
            from .models import SchemaUIConfig

            ui_config = SchemaUIConfig.for_schema_version(
                self._schema_version, project=self._project
            )
            ui_layers = ui_config.layers
            ontology_routing = ui_config.ontology_routing
            widget_overrides = ui_config.widget_overrides
            globally_hidden_slots = ui_config.globally_hidden_slots
            slot_help_texts = ui_config.slot_help_text

        if ontology_routing is None:
            ontology_routing = {}
        if widget_overrides is None:
            widget_overrides = {}
        if slot_help_texts is None:
            slot_help_texts = {}
        if geonames_autofill is None:
            geonames_autofill = {}
        if coordinate_list_fields is None:
            coordinate_list_fields = {}
        hidden = frozenset(globally_hidden_slots or [])

        slot_names = [n for n in self._all_slot_names(class_name) if n not in hidden]
        slot_specs = {}
        for name in slot_names:
            spec = self._slot_spec(
                name,
                class_name,
                ontology_routing,
                widget_overrides,
                slot_help_texts,
                geonames_autofill,
                coordinate_list_fields,
                hidden,
            )
            # Skip slots marked as hidden by loom_role
            if spec is not None:
                slot_specs[name] = spec

        # A coordinate_list widget that successfully embeds its sibling
        # country/state fields (see _slot_spec) renders them itself; drop the
        # bare top-level copies so they don't render a second time via the
        # normal per-slot loop. Only drop them when embedding actually
        # succeeded (geonames_*_field present) so schema versions without a
        # matching coordinate_list slot keep rendering these as plain fields.
        for embedded in list(slot_specs.values()):
            if embedded.get("widget") != "coordinate_list":
                continue
            for slot_key, field_key in (
                ("geonames_country_slot", "geonames_country_field"),
                ("geonames_state_slot", "geonames_state_field"),
            ):
                sibling_name = embedded.get(slot_key)
                if sibling_name and embedded.get(field_key):
                    slot_specs.pop(sibling_name, None)

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
        slot_help_texts: dict | None = None,
        geonames_autofill: dict | None = None,
        coordinate_list_fields: dict | None = None,
        globally_hidden_slots: frozenset | None = None,
    ) -> dict:
        slot = self._sv.induced_slot(slot_name, class_name)
        slot_range = (slot.range or "string").lower()

        # A slot declared as `any_of: [{range: uriorcurie}, {range: string}]`
        # (e.g. entity_term, measured_attribute — CAMO's "ontology term or
        # free text" pattern) reports a base range of "string" from LinkML,
        # which would otherwise fall through to a plain text widget and lose
        # ontology autocomplete entirely. Prefer the uriorcurie/curie member
        # for widget selection; the any_of still permits a plain string value
        # at validation time regardless of which widget renders it.
        any_of_ranges = {
            str(expr.range).lower() for expr in (slot.any_of or []) if expr.range
        }
        if any_of_ranges & {"uriorcurie", "curie"}:
            slot_range = "uriorcurie"

        # Pre-compute enum choices so we can use the count for widget selection.
        _enum_choices: list[dict] = []
        if self._sv.get_enum(slot.range or ""):
            _enum_choices = self._enum_choices(slot.range)

        # Widget classification
        if slot_name in widget_overrides:
            widget = widget_overrides[slot_name]
        elif slot_name in ("subject", "object") and slot_range == "causalnode":
            widget = "node_picker"
        elif slot_range in _PRIMITIVE_WIDGET:
            widget = _PRIMITIVE_WIDGET[slot_range]
        elif self._sv.get_enum(slot.range or ""):
            widget = (
                "enum_autocomplete"
                if len(_enum_choices) > _LARGE_ENUM_THRESHOLD
                else "select"
            )
        elif self._sv.get_class(slot.range or ""):
            widget = "fieldset"
        else:
            widget = "text"

        schema_ontology_prefixes = _ann_list(slot.annotations, "loom_ontologies")
        routing = ontology_routing.get(slot_name, [])

        ontology_condition_slot: str | None = None
        ontology_routes: dict[str, dict] = {}
        allow_free_text = False

        if isinstance(routing, list):
            # Two list shapes are both "sidecar" (non-conditional) routing:
            # the original flat prefix-string list (["ENVO", "ELMO"]) and the
            # form builder's simplified per-item dict list
            # ([{"prefix": "ENVO"}, {"prefix": "ELMO"}]).
            sidecar_ontology_prefixes: list[str] = [
                (item.get("prefix") if isinstance(item, dict) else item)
                for item in routing
            ]
            sidecar_ontology_prefixes = [p for p in sidecar_ontology_prefixes if p]
            wikidata_live: dict | None = None
        elif "condition_slot" in routing:
            # Conditional routing: the widget re-queries with the route
            # matching the current value of a sibling slot (e.g. entity_term's
            # routing depends on entity_type). The "default" route is used as
            # the flattened ontology_prefixes/wikidata_live fallback for any
            # renderer that isn't sibling-aware.
            ontology_condition_slot = routing.get("condition_slot")
            allow_free_text = bool(routing.get("allow_free_text"))
            ontology_routes = {
                str(value): _normalize_route(route)
                for value, route in (routing.get("routes") or {}).items()
            }
            default_route = _normalize_route(routing.get("default") or {})
            sidecar_ontology_prefixes = default_route["prefixes"]
            wikidata_live = default_route["wikidata_live"]
        else:
            sidecar_ontology_prefixes = routing.get("prefixes", [])
            wikidata_live = routing.get("wikidata_live") or None
            allow_free_text = bool(routing.get("allow_free_text"))
        ontology_prefixes = schema_ontology_prefixes or sidecar_ontology_prefixes

        slot_loom_role = _ann_value(slot.annotations, "loom_role")

        spec: dict = {
            "name": slot_name,
            "label": (slot.title or slot_name).replace("_", " ").title(),
            "widget": widget,
            "required": bool(slot.required),
            "multivalued": bool(slot.multivalued),
            "description": slot.description or "",
            "help_text": (slot_help_texts or {}).get(slot_name, ""),
            "ifabsent": slot.ifabsent,
            "ontology_prefixes": ontology_prefixes,
            "wikidata_live": wikidata_live,
            "ontology_condition_slot": ontology_condition_slot,
            "ontology_routes": ontology_routes,
            "allow_free_text": allow_free_text,
            "minimum_value": slot.minimum_value,
            "maximum_value": slot.maximum_value,
            "has_minimum_value": slot.minimum_value is not None,
            "has_maximum_value": slot.maximum_value is not None,
            "minimum_cardinality": getattr(slot, "minimum_cardinality", None),
            "maximum_cardinality": getattr(slot, "maximum_cardinality", None),
            "pattern": slot.pattern or "",
        }

        if widget in ("select", "enum_autocomplete"):
            spec["choices"] = _enum_choices

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
                    slot_help_texts=slot_help_texts,
                    geonames_autofill=geonames_autofill,
                    coordinate_list_fields=coordinate_list_fields,
                    globally_hidden_slots=list(globally_hidden_slots or []),
                )

        if widget == "coordinate_list":
            autofill = (geonames_autofill or {}).get(slot_name) or {}
            sibling_names = set(self._all_slot_names(class_name))
            for slot_key, field_key, autofill_key in (
                ("geonames_country_slot", "geonames_country_field", "country_slot"),
                ("geonames_state_slot", "geonames_state_field", "state_slot"),
            ):
                sibling = autofill.get(autofill_key)
                if not sibling or sibling not in sibling_names:
                    continue
                # Render the sibling field's own spec inline in the widget
                # (see form_field.html) instead of a second time at the
                # slot's normal top-level position — form_spec() drops the
                # top-level copy once it sees this embedded field present.
                sibling_spec = self._slot_spec(
                    sibling,
                    class_name,
                    ontology_routing,
                    widget_overrides,
                    slot_help_texts,
                    geonames_autofill,
                )
                if sibling_spec is not None:
                    spec[slot_key] = sibling
                    spec[field_key] = sibling_spec
            extra_fields = []
            range_class_name = slot.range or ""
            range_slot_names = set(self._all_slot_names(range_class_name))
            for nested_name in (coordinate_list_fields or {}).get(slot_name, []):
                if nested_name not in range_slot_names:
                    continue
                nested_spec = self._slot_spec(
                    nested_name,
                    range_class_name,
                    ontology_routing,
                    widget_overrides,
                    slot_help_texts,
                    geonames_autofill,
                    coordinate_list_fields,
                )
                if nested_spec is not None:
                    extra_fields.append(nested_spec)
            if extra_fields:
                spec["coordinate_item_fields"] = extra_fields

        if widget == "applied_to_list":
            # Pull entity_type choices from the range class (AppliedToEntity)
            # so the template can pass them to the JS widget as a JSON array.
            spec["entity_type_choices"] = []
            range_class = self._sv.get_class(slot.range or "")
            if range_class:
                for inner_slot in self._sv.class_induced_slots(range_class.name):
                    if inner_slot.name == "entity_type" and inner_slot.range:
                        spec["entity_type_choices"] = self._enum_choices(
                            inner_slot.range
                        )
                        break

        # Apply loom_role overrides
        if slot_loom_role == "hidden":
            return None  # Signal to exclude this slot
        if slot_loom_role == "collapse":
            spec["collapsed_by_default"] = True

        return spec

    def _enum_choices(self, enum_name: str) -> list[dict]:
        enum_def = self._sv.get_enum(enum_name)
        if not enum_def:
            return []
        choices = []
        for pv_name, pv in (enum_def.permissible_values or {}).items():
            ann = pv.annotations or {}
            label = (
                _ann_value(ann, "display_label")
                or _ann_value(ann, "preferred_label")
                or pv_name.replace("_", " ").title()
            )
            # `linguistic_cues` and `exemplars` serve the same UI purpose
            # (example phrasing shown as an annotation hint) but different
            # CAMO enums use different annotation names for it (e.g.
            # ClaimStrengthEnum switched to `exemplars` while
            # PhilosophicalAccountEnum still uses `linguistic_cues`) — fall
            # back so the hint renders regardless of which one a given enum
            # happens to use.
            choices.append(
                {
                    "value": pv_name,
                    "label": label,
                    "description": pv.description or "",
                    "linguistic_cues": _ann_value(ann, "linguistic_cues")
                    or _ann_value(ann, "exemplars"),
                    "exemplars": _ann_value(ann, "exemplars"),
                }
            )
        return choices


def _normalize_route(route) -> dict:
    """Normalize one ontology_routing route to {"prefixes": [...], "wikidata_live": {...}|None}."""
    if isinstance(route, list):
        return {"prefixes": route, "wikidata_live": None}
    return {
        "prefixes": route.get("prefixes", []),
        "wikidata_live": route.get("wikidata_live") or None,
    }


def _ann_value(annotations: dict, key: str) -> str:
    """Extract annotation value safely from linkml Annotation objects or plain strings."""
    if not annotations:
        return ""
    v = None
    if hasattr(annotations, "get"):
        v = annotations.get(key)
    if v is None:
        for ann_key, ann_value in _annotation_items(annotations):
            if ann_key == key:
                v = ann_value
                break
    if v is None:
        return ""
    if hasattr(v, "value"):
        return v.value or ""
    return str(v)


def _ann_list(annotations: dict, key: str) -> list[str]:
    """Extract a comma/whitespace separated annotation value as a string list."""
    value = _ann_value(annotations, key)
    if not value:
        return []
    return [
        item.strip()
        for part in str(value).split(",")
        for item in part.split()
        if item.strip()
    ]


def _annotation_items(annotations) -> list[tuple[str, object]]:
    if not annotations:
        return []
    if hasattr(annotations, "items"):
        try:
            return list(annotations.items())
        except TypeError:
            pass
    if hasattr(annotations, "_items"):
        try:
            return list(annotations._items())
        except TypeError:
            pass
    return []
