"""Bind HTML form data to a LinkML class without naming CAMO slots.

The binder uses induced slots from ``SchemaView`` so inherited slot usage,
cardinality, enums, nested classes, numeric bounds, and patterns follow the
graph-pinned schema.  It intentionally returns structured errors instead of
raising on user input.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from linkml_runtime.utils.schemaview import SchemaView


_INTEGER_RANGES = {"integer", "int"}
_FLOAT_RANGES = {"float", "double", "decimal"}
_BOOLEAN_RANGES = {"boolean", "bool"}
_DATE_RANGES = {"date"}
_DATETIME_RANGES = {"datetime"}


@dataclass
class BindingResult:
    data: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def add_error(self, field_name: str, message: str) -> None:
        self.errors.setdefault(field_name, []).append(message)


def bind_form_data(
    schema_view: SchemaView,
    class_name: str,
    form_data: Mapping[str, Any],
    *,
    excluded_slots: set[str] | frozenset[str] | None = None,
) -> BindingResult:
    """Return a typed payload and field errors for a LinkML-backed form."""
    excluded = set(excluded_slots or ())
    raw = _normalise_form_data(form_data)
    result = BindingResult()

    if schema_view.get_class(class_name) is None:
        result.add_error("_form", f"Schema class {class_name!r} does not exist.")
        return result

    for key in raw:
        _validate_path(schema_view, class_name, key, excluded, result)

    result.data = _bind_class(
        schema_view,
        class_name,
        raw,
        result,
        prefix="",
        excluded_slots=excluded,
    )
    return result


def _normalise_form_data(form_data: Mapping[str, Any]) -> dict[str, list[Any]]:
    if hasattr(form_data, "lists"):
        return {str(key): list(values) for key, values in form_data.lists()}
    normalised: dict[str, list[Any]] = {}
    for key, value in form_data.items():
        if isinstance(value, (list, tuple)):
            normalised[str(key)] = list(value)
        else:
            normalised[str(key)] = [value]
    return normalised


def _slot_map(schema_view: SchemaView, class_name: str):
    return {
        slot.name: slot for slot in schema_view.class_induced_slots(class_name)
    }


def _validate_path(
    schema_view: SchemaView,
    class_name: str,
    key: str,
    excluded_slots: set[str],
    result: BindingResult,
) -> None:
    parts = key.split("__")
    current_class = class_name
    position = 0
    while position < len(parts):
        name = parts[position]
        slots = _slot_map(schema_view, current_class)
        slot = slots.get(name)
        if slot is None:
            message = "This field is not defined by the active schema."
            result.add_error(key, message)
            result.add_error("_form", f"{key}: {message}")
            return
        if position == 0 and name in excluded_slots:
            message = "This field is managed by Loom and cannot be posted."
            result.add_error(key, message)
            result.add_error("_form", f"{key}: {message}")
            return
        position += 1
        if position == len(parts):
            if schema_view.get_class(slot.range or "") is not None:
                message = "Use the schema-defined nested fields for this value."
                result.add_error(key, message)
                result.add_error("_form", f"{key}: {message}")
            return

        nested_class = schema_view.get_class(slot.range or "")
        if nested_class is None:
            message = "This field does not accept nested values."
            result.add_error(key, message)
            result.add_error("_form", f"{key}: {message}")
            return
        if slot.multivalued and position < len(parts) and parts[position].isdigit():
            position += 1
        current_class = nested_class.name


def _bind_class(
    schema_view: SchemaView,
    class_name: str,
    raw: dict[str, list[Any]],
    result: BindingResult,
    *,
    prefix: str,
    excluded_slots: set[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for slot in schema_view.class_induced_slots(class_name):
        if not prefix and slot.name in excluded_slots:
            continue
        field_name = f"{prefix}{slot.name}"
        nested_class = schema_view.get_class(slot.range or "")

        if nested_class is not None:
            value = _bind_nested_slot(
                schema_view,
                nested_class.name,
                slot,
                field_name,
                raw,
                result,
            )
        else:
            value = _bind_scalar_slot(schema_view, slot, field_name, raw, result)

        if value is not None and value != [] and value != {}:
            payload[slot.name] = value
        elif slot.required:
            result.add_error(field_name, "This field is required by the schema.")
    return payload


def _bind_nested_slot(
    schema_view: SchemaView,
    nested_class_name: str,
    slot,
    field_name: str,
    raw: dict[str, list[Any]],
    result: BindingResult,
):
    nested_prefix = f"{field_name}__"
    matching = [key for key in raw if key.startswith(nested_prefix)]
    if not matching:
        _validate_cardinality(slot, field_name, 0, result)
        return None

    if not slot.multivalued:
        value = _bind_class(
            schema_view,
            nested_class_name,
            raw,
            result,
            prefix=nested_prefix,
            excluded_slots=set(),
        )
        _validate_cardinality(slot, field_name, 1 if value else 0, result)
        return value

    indices = sorted(
        {
            int(rest.split("__", 1)[0])
            for key in matching
            for rest in [key[len(nested_prefix) :]]
            if rest.split("__", 1)[0].isdigit()
        }
    )
    if not indices:
        indices = [None]

    values = []
    for index in indices:
        item_prefix = nested_prefix if index is None else f"{nested_prefix}{index}__"
        item = _bind_class(
            schema_view,
            nested_class_name,
            raw,
            result,
            prefix=item_prefix,
            excluded_slots=set(),
        )
        if item:
            values.append(item)
    _validate_cardinality(slot, field_name, len(values), result)
    return values


def _bind_scalar_slot(schema_view, slot, field_name, raw, result):
    values = raw.get(field_name, [])
    if slot.multivalued:
        values = _expand_multivalued(values)
        _validate_cardinality(slot, field_name, len(values), result)
        if not values:
            return None
        return [
            _coerce_value(schema_view, slot, field_name, value, result)
            for value in values
        ]

    value = values[-1] if values else None
    if value is None or (isinstance(value, str) and not value.strip()):
        value = _normalise_default(slot.ifabsent)
    if value is None or value == "":
        _validate_cardinality(slot, field_name, 0, result)
        return None
    _validate_cardinality(slot, field_name, 1, result)
    return _coerce_value(schema_view, slot, field_name, value, result)


def _validate_cardinality(slot, field_name: str, count: int, result) -> None:
    minimum = getattr(slot, "minimum_cardinality", None)
    maximum = getattr(slot, "maximum_cardinality", None)
    if minimum is not None and count < minimum:
        result.add_error(field_name, f"Enter at least {minimum} value(s).")
    if maximum is not None and count > maximum:
        result.add_error(field_name, f"Enter no more than {maximum} value(s).")


def _normalise_default(value):
    if not isinstance(value, str):
        return value
    typed = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\((.*)\)", value.strip())
    return typed.group(1) if typed else value


def _expand_multivalued(values: list[Any]) -> list[Any]:
    expanded: list[Any] = []
    for value in values:
        if isinstance(value, str):
            expanded.extend(line.strip() for line in value.splitlines() if line.strip())
        elif value is not None:
            expanded.append(value)
    return expanded


def _coerce_value(schema_view, slot, field_name, value, result):
    slot_range = (slot.range or "string").lower()
    original = value
    try:
        if slot_range in _INTEGER_RANGES:
            value = int(value)
        elif slot_range in _FLOAT_RANGES:
            value = float(value)
        elif slot_range in _BOOLEAN_RANGES:
            value = _coerce_boolean(value)
        elif slot_range in _DATE_RANGES:
            dt.date.fromisoformat(str(value))
            value = str(value)
        elif slot_range in _DATETIME_RANGES:
            dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            value = str(value)
        else:
            value = str(value).strip()
    except (TypeError, ValueError):
        result.add_error(field_name, f"Enter a valid {slot_range} value.")
        return original

    enum = schema_view.get_enum(slot.range or "")
    if enum is not None and value not in (enum.permissible_values or {}):
        result.add_error(field_name, "Select a value defined by the active schema.")

    if slot.minimum_value is not None and isinstance(value, (int, float)):
        if value < slot.minimum_value:
            result.add_error(field_name, f"Value must be at least {slot.minimum_value}.")
    if slot.maximum_value is not None and isinstance(value, (int, float)):
        if value > slot.maximum_value:
            result.add_error(field_name, f"Value must be at most {slot.maximum_value}.")
    if slot.pattern and isinstance(value, str):
        try:
            matches = re.search(slot.pattern, value)
        except re.error:
            result.add_error("_form", f"Schema pattern for {field_name} is invalid.")
        else:
            if matches is None:
                result.add_error(field_name, "Value does not match the schema pattern.")
    return value


def _coerce_boolean(value) -> bool:
    if isinstance(value, bool):
        return value
    normalised = str(value).strip().lower()
    if normalised in {"true", "1", "yes", "on"}:
        return True
    if normalised in {"false", "0", "no", "off"}:
        return False
    raise ValueError("invalid boolean")
