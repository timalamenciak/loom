"""
Phase 6 tests: Schema-driven form input binding.

Verify the input_binding module binds HTML form data to LinkML schema objects
without hardcoding CAMO slot names. Tests use stub SchemaView to remain
schema-agnostic.
"""

import pytest
from linkml_runtime.utils.schemaview import SchemaView

from apps.schemas.input_binding import (
    BindingResult,
    bind_form_data,
)

# ---------------------------------------------------------------------------
# Stub SchemaView fixtures (no database required)
# --------------------------------------------------------------------------


def _make_stub_schema_view(yaml_content: str) -> SchemaView:
    """Create a SchemaView from YAML without database."""
    return SchemaView(yaml_content)


@pytest.fixture
def simple_class_schema():
    """Minimal schema with one class and basic slots."""
    return _make_stub_schema_view("""
id: https://example.org/test
name: test-schema
imports: [linkml:types]

classes:
  TestClass:
    attributes:
      name:
        range: string
        required: true
      value:
        range: integer
      active:
        range: boolean
""")


@pytest.fixture
def enum_class_schema():
    """Schema with enum range."""
    return _make_stub_schema_view("""
id: https://example.org/test
name: test-schema
imports: [linkml:types]

enums:
  StatusEnum:
    permissible_values:
      active:
      inactive:

classes:
  TestClass:
    attributes:
      name:
        range: string
      status:
        range: StatusEnum
""")


@pytest.fixture
def nested_class_schema():
    """Schema with nested class."""
    return _make_stub_schema_view("""
id: https://example.org/test
name: test-schema
imports: [linkml:types]

classes:
  Outer:
    attributes:
      name:
        range: string
      nested:
        range: Inner
  Inner:
    attributes:
      value:
        range: string
        minimum_cardinality: 1
""")


@pytest.fixture
def multivalued_class_schema():
    """Schema with multivalued attributes."""
    return _make_stub_schema_view("""
id: https://example.org/test
name: test-schema
imports: [linkml:types]

classes:
  TestClass:
    attributes:
      name:
        range: string
      tags:
        range: string
        multivalued: true
      tags_required:
        range: string
        multivalued: true
        minimum_cardinality: 1
""")


@pytest.fixture
def bounds_class_schema():
    """Schema with numeric bounds."""
    return _make_stub_schema_view("""
id: https://example.org/test
name: test-schema
imports: [linkml:types]

classes:
  TestClass:
    attributes:
      name:
        range: string
      count:
        range: integer
        minimum_value: 0
        maximum_value: 100
      ratio:
        range: float
        minimum_value: 0.0
        maximum_value: 1.0
""")


@pytest.fixture
def pattern_class_schema():
    """Schema with pattern constraint."""
    return _make_stub_schema_view("""
id: https://example.org/test
name: test-schema
imports: [linkml:types]

classes:
  TestClass:
    attributes:
      email:
        range: string
        pattern: "^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\\\.[a-zA-Z0-9-.]+$"
""")


# ---------------------------------------------------------------------------
# BindingResult tests
# --------------------------------------------------------------------------


class TestBindingResult:
    """Verify BindingResult holds data and errors."""

    def test_initial_state_is_valid(self):
        result = BindingResult()
        assert result.is_valid is True
        assert result.data == {}
        assert result.errors == {}

    def test_add_error(self):
        result = BindingResult()
        result.add_error("field_name", "Error message")

        assert result.is_valid is False
        assert "field_name" in result.errors
        assert result.errors["field_name"] == ["Error message"]

    def test_add_error_multiple(self):
        result = BindingResult()
        result.add_error("field", "First error")
        result.add_error("field", "Second error")

        assert result.errors["field"] == ["First error", "Second error"]


# ---------------------------------------------------------------------------
# bind_form_data tests
# --------------------------------------------------------------------------


class TestBindFormDataBasic:
    """Basic binding without schema edge cases."""

    def test_simple_string_field(self, simple_class_schema):
        form_data = {"name": "Test Value"}

        result = bind_form_data(simple_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert result.data == {"name": "Test Value"}

    def test_integer_conversion(self, simple_class_schema):
        form_data = {"name": "Test", "value": "42"}

        result = bind_form_data(simple_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert result.data == {"name": "Test", "value": 42}

    def test_boolean_conversion(self, simple_class_schema):
        form_data = {"name": "Test", "active": "true"}

        result = bind_form_data(simple_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert result.data == {"name": "Test", "active": True}

    def test_string_active_stays_string(self, simple_class_schema):
        form_data = {"name": "Test", "active": "false"}

        result = bind_form_data(simple_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert result.data == {"name": "Test", "active": False}


class TestBindFormDataRequired:
    """Test required field validation."""

    def test_missing_required_field(self, simple_class_schema):
        form_data = {"value": "42"}  # missing 'name'

        result = bind_form_data(simple_class_schema, "TestClass", form_data)

        assert result.is_valid is False
        assert "name" in result.errors
        assert any("required" in msg for msg in result.errors["name"])

    def test_empty_required_field(self, simple_class_schema):
        form_data = {"name": "   "}  # whitespace only

        result = bind_form_data(simple_class_schema, "TestClass", form_data)

        assert result.is_valid is False

    def test_optional_field_missing(self, simple_class_schema):
        form_data = {"name": "Test"}  # missing 'value' which is optional

        result = bind_form_data(simple_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert "value" not in result.data


class TestBindFormDataEnum:
    """Test enum range validation."""

    def test_enum_valid_value(self, enum_class_schema):
        form_data = {"name": "Test", "status": "active"}

        result = bind_form_data(enum_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert result.data == {"name": "Test", "status": "active"}

    def test_enum_invalid_value(self, enum_class_schema):
        form_data = {"name": "Test", "status": "invalid_status"}

        result = bind_form_data(enum_class_schema, "TestClass", form_data)

        assert result.is_valid is False
        assert "status" in result.errors
        assert any(
            "active" in msg or "inactive" in msg for msg in result.errors["status"]
        )


class TestBindFormDataNested:
    """Test nested class binding."""

    def test_nested_field(self, nested_class_schema):
        form_data = {"name": "Outer", "nested__value": "Inner Value"}

        result = bind_form_data(nested_class_schema, "Outer", form_data)

        assert result.is_valid is True
        assert result.data == {"name": "Outer", "nested": {"value": "Inner Value"}}


class TestBindFormDataMultivalued:
    """Test multivalued attribute binding."""

    def test_multivalued_list_input(self, multivalued_class_schema):
        form_data = {
            "name": "Test",
            "tags": ["tag1", "tag2", "tag3"],
            "tags_required": ["req1"],
        }

        result = bind_form_data(multivalued_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert result.data == {
            "name": "Test",
            "tags": ["tag1", "tag2", "tag3"],
            "tags_required": ["req1"],
        }

    def test_multivalued_string_input(self, multivalued_class_schema):
        form_data = {
            "name": "Test",
            "tags": "tag1\ntag2\ntag3",
            "tags_required": "req1",
        }

        result = bind_form_data(multivalued_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert result.data == {
            "name": "Test",
            "tags": ["tag1", "tag2", "tag3"],
            "tags_required": ["req1"],
        }

    def test_multivalued_minimum_cardinality(self, multivalued_class_schema):
        form_data = {"name": "Test"}  # tags_required is required

        result = bind_form_data(multivalued_class_schema, "TestClass", form_data)

        assert result.is_valid is False
        assert "tags_required" in result.errors

    def test_multivalued_empty_still_valid(self, multivalued_class_schema):
        form_data = {
            "name": "Test",
            "tags_required": [
                "value"
            ],  # tags_required is required, so we provide a value
        }

        result = bind_form_data(multivalued_class_schema, "TestClass", form_data)

        assert result.is_valid is True


class TestBindFormDataBounds:
    """Test numeric bounds validation."""

    def test_within_bounds(self, bounds_class_schema):
        form_data = {"name": "Test", "count": 50, "ratio": 0.5}

        result = bind_form_data(bounds_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert result.data == {"name": "Test", "count": 50, "ratio": 0.5}

    def test_below_minimum(self, bounds_class_schema):
        form_data = {"name": "Test", "count": -5}

        result = bind_form_data(bounds_class_schema, "TestClass", form_data)

        assert result.is_valid is False
        assert "count" in result.errors
        assert any("at least" in msg for msg in result.errors["count"])

    def test_above_maximum(self, bounds_class_schema):
        form_data = {"name": "Test", "ratio": 1.5}

        result = bind_form_data(bounds_class_schema, "TestClass", form_data)

        assert result.is_valid is False
        assert "ratio" in result.errors
        assert any("at most" in msg for msg in result.errors["ratio"])


class TestBindFormDataPattern:
    """Test pattern constraint validation."""

    def test_pattern_matches(self, pattern_class_schema):
        form_data = {"email": "user@example.com"}

        result = bind_form_data(pattern_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert result.data == {"email": "user@example.com"}

    def test_pattern_does_not_match(self, pattern_class_schema):
        form_data = {"email": "not-an-email"}

        result = bind_form_data(pattern_class_schema, "TestClass", form_data)

        assert result.is_valid is False
        assert "email" in result.errors
        assert any("pattern" in msg for msg in result.errors["email"])


class TestBindFormDataInvalidSchema:
    """Test schema validation edge cases."""

    def test_unknown_class(self, simple_class_schema):
        form_data = {"name": "Test"}

        result = bind_form_data(simple_class_schema, "UnknownClass", form_data)

        assert result.is_valid is False
        assert "_form" in result.errors
        assert any("UnknownClass" in msg for msg in result.errors["_form"])

    def test_excluded_slot(self, simple_class_schema):
        form_data = {"name": "Test"}

        result = bind_form_data(
            simple_class_schema,
            "TestClass",
            form_data,
            excluded_slots={"name"},
        )

        assert result.is_valid is False  # name is required


class TestBindFormDataSpecialCases:
    """Test edge cases and special inputs."""

    def test_whitespace_string(self, simple_class_schema):
        form_data = {"name": "  test  "}  # should be stripped

        result = bind_form_data(simple_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert result.data == {"name": "test"}

    def test_none_value(self, simple_class_schema):
        form_data = {"name": None}

        result = bind_form_data(simple_class_schema, "TestClass", form_data)

        assert result.is_valid is False  # None treated as missing for required

    def test_empty_string_optional(self, simple_class_schema):
        form_data = {"name": "Test", "value": ""}  # optional string

        result = bind_form_data(simple_class_schema, "TestClass", form_data)

        assert result.is_valid is True
        assert "value" not in result.data  # empty optional → None
