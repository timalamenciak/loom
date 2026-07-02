"""Tests for apps/annotation/rollup.py"""

import pytest


class TestRollUpSourceDocument:
    """Test the roll_up_source_document function."""

    def test_empty_rules(self):
        from apps.annotation.rollup import roll_up_source_document

        result = roll_up_source_document([], [], [])
        assert result == {}

    def test_invalid_source_skipped(self):
        from apps.annotation.rollup import roll_up_source_document

        rules = [{"slot": "test_slot", "source": "invalid", "attribute": "field"}]
        result = roll_up_source_document([], [], rules)
        assert result == {}

    def test_missing_slot_skipped(self):
        from apps.annotation.rollup import roll_up_source_document

        rules = [{"source": "node", "attribute": "field"}]
        result = roll_up_source_document([{"field": "value"}], [], rules)
        assert result == {}

    def test_missing_attribute_skipped(self):
        from apps.annotation.rollup import roll_up_source_document

        rules = [{"slot": "test_slot", "source": "node"}]
        result = roll_up_source_document([{"field": "value"}], [], rules)
        assert result == {}

    def test_node_list_unique(self):
        from apps.annotation.rollup import roll_up_source_document

        nodes_data = [
            {"entity_type": "plant"},
            {"entity_type": "animal"},
            {"entity_type": "plant"},
        ]
        rules = [{"slot": "entity_types", "source": "node", "attribute": "entity_type"}]
        result = roll_up_source_document(nodes_data, [], rules)
        assert result == {"entity_types": ["plant", "animal"]}

    def test_node_list_all(self):
        from apps.annotation.rollup import roll_up_source_document

        nodes_data = [
            {"entity_type": "plant"},
            {"entity_type": "animal"},
            {"entity_type": "plant"},
        ]
        rules = [
            {
                "slot": "entity_types",
                "source": "node",
                "attribute": "entity_type",
                "operation": "list_all",
            }
        ]
        result = roll_up_source_document(nodes_data, [], rules)
        assert result == {"entity_types": ["plant", "animal", "plant"]}

    def test_edge_list_unique(self):
        from apps.annotation.rollup import roll_up_source_document

        edges_data = [{"predicate": "eats"}, {"predicate": "pollinates"}]
        rules = [{"slot": "predicates", "source": "edge", "attribute": "predicate"}]
        result = roll_up_source_document([], edges_data, rules)
        assert result == {"predicates": ["eats", "pollinates"]}

    def test_nested_attribute(self):
        from apps.annotation.rollup import roll_up_source_document

        nodes_data = [{"mediation": {"has_mediator": "true"}}]
        rules = [
            {"slot": "mediators", "source": "node", "attribute": "mediation.has_mediator"}
        ]
        result = roll_up_source_document(nodes_data, [], rules)
        assert result == {"mediators": ["true"]}

    def test_list_unique_keeps_order(self):
        from apps.annotation.rollup import roll_up_source_document

        nodes_data = [
            {"field": "a"},
            {"field": "b"},
            {"field": "c"},
            {"field": "a"},
        ]
        rules = [{"slot": "fields", "source": "node", "attribute": "field"}]
        result = roll_up_source_document(nodes_data, [], rules)
        assert result == {"fields": ["a", "b", "c"]}

    def test_null_and_empty_values_excluded(self):
        from apps.annotation.rollup import roll_up_source_document

        nodes_data = [
            {"field": "value1"},
            {"field": None},
            {"field": ""},
            {"field": "value2"},
        ]
        rules = [{"slot": "fields", "source": "node", "attribute": "field"}]
        result = roll_up_source_document(nodes_data, [], rules)
        assert result == {"fields": ["value1", "value2"]}

    def test_multiple_rules(self):
        from apps.annotation.rollup import roll_up_source_document

        nodes_data = [{"type": "A", "category": "X"}]
        edges_data = [{"type": "B"}]
        rules = [
            {"slot": "node_types", "source": "node", "attribute": "type"},
            {"slot": "edge_types", "source": "edge", "attribute": "type"},
        ]
        result = roll_up_source_document(nodes_data, edges_data, rules)
        assert result == {"node_types": ["A"], "edge_types": ["B"]}


class TestGetNested:
    """Test the _get_nested helper function."""

    def test_flat_key(self):
        from apps.annotation.rollup import _get_nested

        d = {"field": "value"}
        assert _get_nested(d, "field") == "value"

    def test_nested_path(self):
        from apps.annotation.rollup import _get_nested

        d = {"level1": {"level2": {"level3": "value"}}}
        assert _get_nested(d, "level1.level2.level3") == "value"

    def test_missing_key(self):
        from apps.annotation.rollup import _get_nested

        d = {"field": "value"}
        assert _get_nested(d, "missing") is None

    def test_missing_nested(self):
        from apps.annotation.rollup import _get_nested

        d = {"level1": {"field": "value"}}
        assert _get_nested(d, "level1.missing") is None

    def test_path_through_non_dict(self):
        from apps.annotation.rollup import _get_nested

        d = {"field": "value"}
        assert _get_nested(d, "field.nested") is None


class TestValidateRollupRules:
    """Test the validate_rollup_rules function."""

    def test_valid_rules(self):
        from apps.annotation.rollup import validate_rollup_rules

        rules = [
            {"slot": "slot1", "source": "node", "attribute": "field1"},
            {"slot": "slot2", "source": "edge", "attribute": "field2"},
        ]
        errors = validate_rollup_rules(rules)
        assert errors == []

    def test_non_list_input(self):
        from apps.annotation.rollup import validate_rollup_rules

        errors = validate_rollup_rules("not a list")
        assert errors == ["Rules must be a list."]

    def test_non_dict_rule(self):
        from apps.annotation.rollup import validate_rollup_rules

        rules = ["not a dict"]
        errors = validate_rollup_rules(rules)
        assert errors == ["Rule 1: must be an object."]

    def test_missing_slot(self):
        from apps.annotation.rollup import validate_rollup_rules

        rules = [{"source": "node", "attribute": "field"}]
        errors = validate_rollup_rules(rules)
        assert "Rule 1: 'slot' is required." in errors

    def test_duplicate_slot(self):
        from apps.annotation.rollup import validate_rollup_rules

        rules = [
            {"slot": "slot1", "source": "node", "attribute": "field1"},
            {"slot": "slot1", "source": "edge", "attribute": "field2"},
        ]
        errors = validate_rollup_rules(rules)
        assert "Rule 2: duplicate slot 'slot1'." in errors

    def test_invalid_source(self):
        from apps.annotation.rollup import validate_rollup_rules

        rules = [{"slot": "slot1", "source": "invalid", "attribute": "field"}]
        errors = validate_rollup_rules(rules)
        assert "Rule 1: 'source' must be 'node' or 'edge'." in errors

    def test_missing_attribute(self):
        from apps.annotation.rollup import validate_rollup_rules

        rules = [{"slot": "slot1", "source": "node"}]
        errors = validate_rollup_rules(rules)
        assert "Rule 1: 'attribute' is required." in errors

    def test_invalid_operation(self):
        from apps.annotation.rollup import validate_rollup_rules

        rules = [
            {"slot": "slot1", "source": "node", "attribute": "field", "operation": "invalid"}
        ]
        errors = validate_rollup_rules(rules)
        assert len(errors) == 1
        assert "operation" in errors[0]
        assert "list_unique" in errors[0]
        assert "list_all" in errors[0]
