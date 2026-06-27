from django import template

register = template.Library()


@register.filter
def dict_get(d, key):
    """Get a value from a dict by dynamic key (variable name).

    Supports __ for one level of nested access:
      data|dict_get:'mediation__has_mediator'
      → data['mediation']['has_mediator']
    """
    if not isinstance(d, dict):
        return ""
    key = str(key)
    if "__" in key:
        parent, child = key.split("__", 1)
        val = d.get(parent)
        if isinstance(val, dict):
            return val.get(child, "")
        return ""
    val = d.get(key)
    return "" if val is None else val


@register.filter
def is_checked(value):
    """Return whether a schema boolean value should render as checked."""
    if value is True:
        return True
    return str(value).strip().lower() in {"true", "1", "yes", "on"}
