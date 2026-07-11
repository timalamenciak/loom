"""Tests for the schema-agnostic system-prompt builder.

Fixtures below hand-craft the shape LoomSchemaView.form_spec(class_name)
actually returns: a list of layer dicts, each with a "slots" list of slot
spec dicts (name/required/multivalued/widget/description/choices/
ontology_prefixes/nested_spec — see apps/schemas/schema_engine.py::_slot_spec).
This is a pure string-building unit test, so it doesn't need a real schema —
just realistic input shapes.
"""

from apps.llm.prompt_builder import build_system_prompt


def _node_layers():
    return [
        {
            "id": "elmo",
            "label": "Entity",
            "collapsed_by_default": False,
            "slots": [
                {
                    "name": "entity_term",
                    "required": True,
                    "multivalued": False,
                    "widget": "text",
                    "description": "The biological entity involved in the claim.",
                    "ontology_prefixes": ["ENVO", "ELMO"],
                },
                {
                    "name": "direction",
                    "required": False,
                    "multivalued": False,
                    "widget": "select",
                    "description": "Direction of change in the entity.",
                    "choices": [
                        {
                            "value": "increase",
                            "label": "Increase",
                            "description": "The entity increases.",
                        },
                        {
                            "value": "decrease",
                            "label": "Decrease",
                            "description": "The entity decreases.",
                        },
                    ],
                },
            ],
        }
    ]


def _edge_layers():
    return [
        {
            "id": "claim",
            "label": "Claim strength",
            "collapsed_by_default": False,
            "slots": [
                {
                    "name": "claim_strength",
                    "required": True,
                    "multivalued": False,
                    "widget": "select",
                    "description": "How strongly the causal claim is asserted.",
                    "choices": [
                        {
                            "value": "tendency",
                            "label": "Tendency",
                            "description": "A general tendency, not a strict law.",
                        },
                    ],
                },
            ],
        }
    ]


class TestBuildSystemPrompt:
    def test_prompt_contains_all_visible_slots(self):
        prompt = build_system_prompt(
            {"CausalNode": _node_layers(), "CausalEdge": _edge_layers()}
        )
        assert "entity_term" in prompt
        assert "direction" in prompt
        assert "claim_strength" in prompt

    def test_prompt_excludes_hidden_slots(self):
        # form_spec() already drops globally_hidden_slots before returning —
        # a slot that was hidden simply never appears in the input dict, so
        # the builder must not invent it either.
        prompt = build_system_prompt(
            {"CausalNode": _node_layers(), "CausalEdge": _edge_layers()}
        )
        assert "internal_audit_id" not in prompt

    def test_prompt_includes_enum_values(self):
        prompt = build_system_prompt({"CausalEdge": _edge_layers()})
        assert "tendency" in prompt
        assert "A general tendency, not a strict law." in prompt

    def test_prompt_format_instruction_present(self):
        prompt = build_system_prompt(
            {"CausalNode": _node_layers(), "CausalEdge": _edge_layers()}
        )
        assert "JSON" in prompt
        assert "subject" in prompt
        assert "object" in prompt
        assert "edge" in prompt
        assert "source_text" in prompt

    def test_prompt_describes_ontology_routing(self):
        prompt = build_system_prompt({"CausalNode": _node_layers()})
        assert "ENVO" in prompt
        assert "ELMO" in prompt

    def test_prompt_marks_required_slots(self):
        prompt = build_system_prompt({"CausalNode": _node_layers()})
        assert "entity_term (required" in prompt
        assert "direction (optional" in prompt

    def test_prompt_does_not_hardcode_class_names(self):
        """The builder must work for an arbitrary schema, not just CAMO's
        class names — pass something that looks nothing like CausalNode/
        CausalEdge and confirm it still renders."""
        prompt = build_system_prompt(
            {
                "Widget": [
                    {
                        "id": "main",
                        "label": "Main",
                        "collapsed_by_default": False,
                        "slots": [
                            {
                                "name": "widget_color",
                                "required": True,
                                "multivalued": False,
                                "widget": "text",
                                "description": "The widget's color.",
                            }
                        ],
                    }
                ]
            }
        )
        assert "Widget fields" in prompt
        assert "widget_color" in prompt
