"""
Phase 6 tests: Graph migration report generation.

Verify the migrate_graph command diffs schema versions and reports
migration impact on graphs. Tests are pure Python - no database required
for logic, use database fixtures for integration.
"""

from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

# ---------------------------------------------------------------------------
# Unit tests: pure functions
# --------------------------------------------------------------------------


class TestMigrationCommandHelpers:
    """Verify migration command helper functions."""

    def test_slot_names(self):
        from apps.export.management.commands.migrate_graph import _slot_names

        schema_version = Mock()
        schema_version.linkml_yaml = """
id: https://example.org/test
name: test
imports: [linkml:types]
classes:
  TestClass:
    attributes:
      field1:
        range: string
      field2:
        range: integer
"""

        slots = _slot_names(schema_version)

        assert slots == {"field1", "field2"}

    def test_slot_names_empty(self):
        from apps.export.management.commands.migrate_graph import _slot_names

        schema_version = Mock()
        schema_version.linkml_yaml = """
id: https://example.org/test
name: test
imports: [linkml:types]
classes:
  TestClass:
    attributes: {}
"""

        slots = _slot_names(schema_version)

        assert slots == set()

    def test_enum_values(self):
        from apps.export.management.commands.migrate_graph import _enum_values

        schema_version = Mock()
        schema_version.linkml_yaml = """
id: https://example.org/test
name: test
imports: [linkml:types]
enums:
  StatusEnum:
    permissible_values:
      active:
      inactive:
      pending:
"""

        enums = _enum_values(schema_version)

        assert enums == {"StatusEnum": {"active", "inactive", "pending"}}

    def test_enum_values_empty(self):
        from apps.export.management.commands.migrate_graph import _enum_values

        schema_version = Mock()
        schema_version.linkml_yaml = """
id: https://example.org/test
name: test
imports: [linkml:types]
enums: {}
"""

        enums = _enum_values(schema_version)

        assert enums == {}

    def test_has_value_simple(self):
        from apps.export.management.commands.migrate_graph import _has_value

        data = {"field1": "value1", "field2": "value2"}

        assert _has_value(data, "field1") is True
        assert _has_value(data, "field2") is True
        assert _has_value(data, "missing") is False

    def test_has_value_empty_string(self):
        from apps.export.management.commands.migrate_graph import _has_value

        data = {"field": ""}

        assert _has_value(data, "field") is False

    def test_has_value_empty_list(self):
        from apps.export.management.commands.migrate_graph import _has_value

        data = {"field": []}

        assert _has_value(data, "field") is False

    def test_has_value_empty_dict(self):
        from apps.export.management.commands.migrate_graph import _has_value

        data = {"field": {}}

        assert _has_value(data, "field") is False

    def test_has_value_nested(self):
        from apps.export.management.commands.migrate_graph import _has_value

        data = {"nested": {"field": "value"}}

        assert _has_value(data, "nested__field") is True
        assert _has_value(data, "nested__missing") is False

    def test_has_value_nested_not_dict(self):
        from apps.export.management.commands.migrate_graph import _has_value

        data = {"nested": "not a dict"}

        assert _has_value(data, "nested__field") is False


# ---------------------------------------------------------------------------
# Integration tests: command execution
# --------------------------------------------------------------------------


class TestMigrateGraphCommand:
    """Verify migrate_graph command execution."""

    def test_graph_not_found(self):
        """Command raises error for non-existent graph."""
        with pytest.raises(CommandError) as exc_info:
            call_command("migrate_graph", "99999", "--to-version", "0.5.0")

        assert "not found" in str(exc_info.value).lower()

    def test_schema_version_not_found(self, db):
        """Command raises error for non-existent schema version."""
        from apps.annotation.models import CausalGraph
        from apps.schemas.models import SchemaVersion

        # Create a graph with a valid schema
        schema = SchemaVersion.objects.create(
            name="Test Schema",
            version="0.4.0",
            linkml_yaml="# minimal schema",
            sha256="a" * 64,
        )
        graph = CausalGraph.objects.create(
            schema_version=schema,
            source_document={},
        )

        with pytest.raises(CommandError) as exc_info:
            call_command("migrate_graph", str(graph.pk), "--to-version", "9.9.9")

        assert "not found" in str(exc_info.value).lower()

    def test_same_schema_version(self, db):
        """Command warns when source and target schemas are the same."""
        from apps.annotation.models import CausalGraph
        from apps.schemas.models import SchemaVersion

        schema = SchemaVersion.objects.create(
            name="Test Schema",
            version="0.4.0",
            linkml_yaml="# minimal schema",
            sha256="a" * 64,
        )
        graph = CausalGraph.objects.create(
            schema_version=schema,
            source_document={},
        )

        out, err = call_command("migrate_graph", str(graph.pk), "--to-version", "0.4.0")

        # Should output warning
        assert "already on this schema" in out.lower() or "already on" in out.lower()

    def test_report_generated(self, db, capsys):
        """Command generates migration report."""
        from apps.annotation.models import CausalGraph, Edge, Node
        from apps.schemas.models import SchemaVersion

        # Create old schema
        old_schema = SchemaVersion.objects.create(
            name="Old Schema",
            version="0.4.0",
            linkml_yaml="""
id: https://example.org/camo
name: camo
imports: [linkml:types]
classes:
  CausalNode:
    attributes:
      name:
        range: string
  CausalEdge:
    attributes:
      predicate:
        range: string
      removed_field:
        range: string
""",
            sha256="a" * 64,
        )

        # Create new schema with removed field
        SchemaVersion.objects.create(
            name="New Schema",
            version="0.5.0",
            linkml_yaml="""
id: https://example.org/camo
name: camo
imports: [linkml:types]
classes:
  CausalNode:
    attributes:
      name:
        range: string
  CausalEdge:
    attributes:
      predicate:
        range: string
""",
            sha256="b" * 64,
        )

        graph = CausalGraph.objects.create(
            schema_version=old_schema,
            source_document={},
        )

        node = Node.objects.create(
            graph=graph,
            name="Test Node",
            category="entity",
            data={"name": "Test Node", "removed_field": "value"},
            schema_version=old_schema,
        )

        edge = Edge.objects.create(
            graph=graph,
            subject=node,
            object=node,
            predicate="causal",
            data={"predicate": "causal", "removed_field": "edge value"},
            schema_version=old_schema,
        )

        out, err = call_command(
            "migrate_graph", str(graph.pk), "--to-version", "0.5.0", "--report"
        )

        # Should mention removed field
        assert "removed_field" in out or "removed" in out.lower()

        # Should mention affected node
        assert "Test Node" in out or "affected" in out.lower()

    def test_no_breaking_changes(self, db, capsys):
        """Command reports no action required for safe migrations."""
        from apps.annotation.models import CausalGraph
        from apps.schemas.models import SchemaVersion

        schema = SchemaVersion.objects.create(
            name="Test Schema",
            version="0.5.0",
            linkml_yaml="""
id: https://example.org/camo
name: camo
imports: [linkml:types]
classes:
  CausalNode:
    attributes:
      name:
        range: string
""",
            sha256="a" * 64,
        )

        graph = CausalGraph.objects.create(
            schema_version=schema,
            source_document={},
        )

        out, err = call_command(
            "migrate_graph", str(graph.pk), "--to-version", "0.5.0", "--report"
        )

        assert "no breaking" in out.lower() or "safe" in out.lower()
