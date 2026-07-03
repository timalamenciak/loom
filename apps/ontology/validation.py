"""Generic validation for schema-derived ontology autocomplete values."""

from __future__ import annotations

from .services import terms_by_curies


def add_ontology_errors(binding, form_spec: list[dict], snapshot) -> None:
    """Add snapshot-membership errors to a schema binding result in place."""

    # Legacy/unconfigured projects remain editable. The UI surfaces that their
    # cache is unavailable; strict membership begins once a snapshot is pinned.
    if snapshot is None:
        return
    fields = _ontology_fields(binding.data, form_spec)
    local_curies = sorted(
        {
            value
            for field in fields
            for value in field[1]
            if field[2] and not value.startswith("WD:")
        }
    )
    known = {
        term.curie: term for term in terms_by_curies(local_curies, snapshot=snapshot)
    }
    for field_name, values, prefixes, allow_free_text in fields:
        if not prefixes:
            continue
        for value in values:
            if value.startswith("WD:"):
                continue
            prefix = value.split(":", 1)[0] if ":" in value else ""
            # A slot with allow_free_text (e.g. entity_term, measured_attribute)
            # accepts a plain string when nothing cached matches yet — an
            # OntologyTermSuggestion is logged separately for curator review.
            # Only enforce membership when the value actually looks like a
            # CURIE for one of this slot's routed prefixes; anything else is
            # deliberate free text, not a malformed ontology reference.
            if allow_free_text and (not prefix or prefix not in prefixes):
                continue
            if not prefix or value not in known:
                binding.add_error(
                    field_name,
                    "Select a term from an ontology loaded for this graph.",
                )
            elif prefixes and prefix not in prefixes:
                binding.add_error(
                    field_name,
                    f"Select a term from: {', '.join(prefixes)}.",
                )


def _ontology_fields(data: dict, form_spec: list[dict], prefix: str = "") -> list:
    found = []
    for layer in form_spec:
        for slot in layer.get("slots", []):
            name = slot["name"]
            field_name = f"{prefix}{name}"
            value = data.get(name)
            if slot.get("widget") == "ontology_autocomplete" and value:
                values = value if isinstance(value, list) else [value]
                found.append(
                    (
                        field_name,
                        [str(item).strip() for item in values if str(item).strip()],
                        list(slot.get("ontology_prefixes") or []),
                        bool(slot.get("allow_free_text")),
                    )
                )
            nested = slot.get("nested_spec")
            if not nested or not value:
                continue
            if isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, dict):
                        found.extend(
                            _ontology_fields(
                                item, nested, prefix=f"{field_name}__{index}__"
                            )
                        )
            elif isinstance(value, dict):
                found.extend(_ontology_fields(value, nested, prefix=f"{field_name}__"))
    return found
