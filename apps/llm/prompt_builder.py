"""Schema-agnostic system-prompt builder for the LLM proposal seam.

Turns LoomSchemaView.form_spec() output into a system prompt Claude can use
to extract causal claims under whatever LinkML schema is currently active —
nothing here names a CAMO slot or class; every field name, constraint, enum
value, and ontology-routing hint is read out of the form spec's own dicts
(see "The one defining constraint" in CLAUDE.md). When CAMO adds a slot, this
prompt picks it up automatically the next time it's built from the active
schema's form_spec() — no code change here.
"""

from __future__ import annotations

import json


def _slot_lines(slots: list[dict], indent: str = "") -> list[str]:
    lines = []
    for slot in slots:
        name = slot.get("name", "")
        if not name:
            continue
        required = "required" if slot.get("required") else "optional"
        cardinality = "multi-valued" if slot.get("multivalued") else "single-valued"
        widget = slot.get("widget", "text")
        description = (slot.get("description") or "").strip()

        line = f"{indent}- {name} ({required}, {cardinality}, {widget})"
        if description:
            line += f": {description}"
        lines.append(line)

        choices = slot.get("choices") or []
        if choices:
            rendered = "; ".join(
                choice.get("value", "")
                + (f" — {choice['description']}" if choice.get("description") else "")
                for choice in choices
            )
            lines.append(f"{indent}  Allowed values: {rendered}")

        prefixes = slot.get("ontology_prefixes") or []
        if prefixes:
            lines.append(f"{indent}  Use a CURIE from prefixes: {', '.join(prefixes)}")

        nested = slot.get("nested_spec")
        if nested:
            lines.append(f"{indent}  Structured sub-fields:")
            for layer in nested:
                lines.extend(_slot_lines(layer.get("slots", []), indent + "    "))
    return lines


def _class_section(class_name: str, layers: list[dict]) -> list[str]:
    lines = [f"## {class_name} fields", ""]
    for layer in layers:
        label = layer.get("label") or layer.get("id") or ""
        if label:
            lines.append(f"### {label}")
        lines.extend(_slot_lines(layer.get("slots", [])))
        lines.append("")
    return lines


def build_system_prompt(class_specs: dict[str, list[dict]]) -> str:
    """Build a system prompt describing every slot in *class_specs*.

    class_specs maps a schema class name (e.g. "CausalNode", "CausalEdge")
    to the list of layer dicts LoomSchemaView.form_spec(class_name) returns
    for that class. Hidden slots never appear here because form_spec()
    already excludes globally_hidden_slots before returning — this function
    only ever describes what it's handed.
    """
    lines = [
        "You extract causal claims from scientific text.",
        "",
        "Given a passage, identify the causal relationships it expresses and "
        "represent each one as a subject node, an object node, and an edge "
        "connecting them, using exactly the fields described below. Every "
        "field name below is authoritative for this task — do not invent "
        "field names that aren't listed, and do not fill a field you have no "
        "textual evidence for.",
        "",
    ]

    for class_name, layers in class_specs.items():
        lines.extend(_class_section(class_name, layers))

    lines.extend(
        [
            "## Output format",
            "",
            "Respond with a JSON array. Each element is an object with these keys:",
            "- subject: an object with the node fields above, describing the causal subject",
            "- object: an object with the node fields above, describing the causal object",
            "- edge: an object with the edge fields above, describing the causal relationship",
            "- source_text: the exact quoted sentence (or span) from the passage that "
            "expresses this claim",
            "",
            "Return only the JSON array — no surrounding prose, no markdown code fences.",
        ]
    )

    return "\n".join(lines)


def serialize_example(edge) -> dict:
    """Render *edge* in the same JSON shape the model is asked to produce —
    see the "## Output format" section build_system_prompt() emits."""
    return {
        "subject": {"name": edge.subject.name, **edge.subject.data},
        "object": {"name": edge.object.name, **edge.object.data},
        "edge": {**edge.data},
        "source_text": edge.data.get("original_sentence", ""),
    }


def build_few_shot_messages(examples: list) -> list[dict]:
    """Turn approved FewShotExamples into alternating user/assistant turns
    a caller prepends before the main extraction request."""
    messages: list[dict] = []
    for example in examples:
        edge = example.edge
        source_text = edge.data.get("original_sentence", "")
        messages.append(
            {"role": "user", "content": f"Extract claims from: {source_text}"}
        )
        messages.append(
            {"role": "assistant", "content": json.dumps(serialize_example(edge))}
        )
    return messages
