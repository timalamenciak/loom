"""Tests for SchemaUIConfig.for_schema_version() three-level fallback."""

import pytest

from apps.schemas.models import SchemaUIConfig, SchemaVersion


@pytest.fixture
def schema_version(db):
    return SchemaVersion.objects.create(
        version="test-ui-config",
        linkml_yaml="id: https://example.org/test\nname: test\n",
        is_active=False,
    )


@pytest.fixture
def project(db):
    from django.contrib.auth import get_user_model

    from apps.projects.models import Project

    user = get_user_model().objects.create_user("ui_config_user", password="x")
    return Project.objects.create(name="UI Config Test Project", created_by=user)


class TestSchemaUIConfigFallback:
    def test_fallback_to_yaml(self, schema_version):
        """No DB record exists → transient instance parsed from loom_ui.yaml."""
        result = SchemaUIConfig.for_schema_version(schema_version)

        assert result.pk is None, "transient instance must not be persisted"
        assert isinstance(result.layers, list)
        assert len(result.layers) > 0, "loom_ui.yaml layers must not be empty"
        assert isinstance(result.ontology_routing, dict)
        assert isinstance(result.widget_overrides, dict)

    def test_schema_level_record(self, schema_version, project):
        """Schema-level DB record is returned when no project-level record exists."""
        record = SchemaUIConfig.objects.create(
            schema_version=schema_version,
            project=None,
            layers=[{"id": "schema_layer", "slots": []}],
            ontology_routing={"my_slot": ["ENVO"]},
            widget_overrides={},
            globally_hidden_slots=["id"],
            slot_help_text={},
        )

        result = SchemaUIConfig.for_schema_version(schema_version, project=project)

        assert result.pk == record.pk
        assert result.layers == [{"id": "schema_layer", "slots": []}]

    def test_project_override_shadows_schema(self, schema_version, project):
        """Project-level DB record is returned when both project and schema records exist."""
        SchemaUIConfig.objects.create(
            schema_version=schema_version,
            project=None,
            layers=[{"id": "schema_layer", "slots": []}],
            ontology_routing={},
            widget_overrides={},
            globally_hidden_slots=[],
            slot_help_text={},
        )
        project_record = SchemaUIConfig.objects.create(
            schema_version=schema_version,
            project=project,
            layers=[{"id": "project_layer", "slots": []}],
            ontology_routing={},
            widget_overrides={},
            globally_hidden_slots=[],
            slot_help_text={},
        )

        result = SchemaUIConfig.for_schema_version(schema_version, project=project)

        assert result.pk == project_record.pk
        assert result.layers == [{"id": "project_layer", "slots": []}]
