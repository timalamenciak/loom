import json

from django import template

register = template.Library()


@register.filter
def dict_get(d, key):
    """Get a value from a dict by dynamic key (variable name).

    Supports ``__`` traversal through nested dictionaries and indexed lists:
      data|dict_get:'mediation__has_mediator'
      → data['mediation']['has_mediator']
    """
    key = str(key)
    if isinstance(d, dict) and key in d:
        value = d[key]
        return "" if value is None else value
    value = d
    for part in key.split("__"):
        if isinstance(value, dict):
            value = value.get(part, "")
        elif isinstance(value, (list, tuple)) and part.isdigit():
            index = int(part)
            value = value[index] if index < len(value) else ""
        else:
            return ""
    val = value
    return "" if val is None else val


@register.filter
def is_checked(value):
    """Return whether a schema boolean value should render as checked."""
    if value is True:
        return True
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


@register.filter
def to_json(value):
    """Serialize *value* to a JSON string for embedding in a data-* attribute.

    Django's template auto-escaping will HTML-encode the result (replacing
    ``"`` with ``&quot;`` etc.), which is correct for attribute values — the
    browser HTML-decodes before the JS reads it, so JSON.parse() receives the
    original string.
    """
    return json.dumps(value, ensure_ascii=True)


@register.filter
def join_lines(value):
    """Render a multivalued scalar as one editable value per line."""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item) for item in value)
    return "" if value is None else str(value)
