"""Rollup engine: aggregate node/edge attributes into SourceDocument slots.

SourceDocument receives special treatment in Loom as an aggregation target for
node/edge JSONB attribute paths. This breaks schema-agnosticism deliberately;
see CLAUDE.md for the rationale and documentation.
"""

KNOWN_OPERATIONS = frozenset({"list_unique", "list_all"})
KNOWN_SOURCES = frozenset({"node", "edge"})


def roll_up_source_document(
    nodes_data: list[dict],
    edges_data: list[dict],
    rules: list[dict],
) -> dict:
    """Apply *rules* against *nodes_data* / *edges_data*; return slot → list mapping."""
    result: dict = {}
    for rule in rules:
        slot = rule.get("slot")
        source = rule.get("source")
        attribute = rule.get("attribute")
        operation = rule.get("operation", "list_unique")

        if not slot or source not in KNOWN_SOURCES or not attribute:
            continue

        items = nodes_data if source == "node" else edges_data
        values: list[str] = []
        for data in items:
            v = _get_nested(data, attribute)
            if isinstance(v, list):
                values.extend(str(x) for x in v if x is not None and x != "")
            elif v is not None and v != "":
                values.append(str(v))

        if operation == "list_unique":
            seen: set[str] = set()
            deduped: list[str] = []
            for v in values:
                if v not in seen:
                    seen.add(v)
                    deduped.append(v)
            result[slot] = deduped
        else:
            result[slot] = values

    return result


def _get_nested(d: dict, path: str):
    """Resolve a dot-separated path through a nested dict."""
    parts = path.split(".")
    current = d
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def validate_rollup_rules(rules: list) -> list[str]:
    """Return a list of error strings, or an empty list if valid."""
    errors: list[str] = []
    if not isinstance(rules, list):
        return ["Rules must be a list."]
    seen_slots: set[str] = set()
    for i, rule in enumerate(rules):
        prefix = f"Rule {i + 1}"
        if not isinstance(rule, dict):
            errors.append(f"{prefix}: must be an object.")
            continue
        slot = rule.get("slot", "")
        if not slot:
            errors.append(f"{prefix}: 'slot' is required.")
        elif slot in seen_slots:
            errors.append(f"{prefix}: duplicate slot '{slot}'.")
        else:
            seen_slots.add(slot)
        if rule.get("source") not in KNOWN_SOURCES:
            errors.append(f"{prefix}: 'source' must be 'node' or 'edge'.")
        if not rule.get("attribute"):
            errors.append(f"{prefix}: 'attribute' is required.")
        operation = rule.get("operation", "list_unique")
        if operation not in KNOWN_OPERATIONS:
            errors.append(
                f"{prefix}: 'operation' must be one of: {', '.join(sorted(KNOWN_OPERATIONS))}."
            )
    return errors
