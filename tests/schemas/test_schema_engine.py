"""Tests for project-bound LoomSchemaView / SchemaUIConfig wiring.

See tests/test_schemas.py for the broader engine-mechanics suite; this file
covers only the project-config-in-form_spec() behavior added alongside
LoomSchemaView.__init__(project=...).
"""

import pytest

from apps.schemas.models import SchemaUIConfig
from apps.schemas.schema_engine import LoomSchemaView


@pytest.fixture
def project(db):
    from django.contrib.auth import get_user_model

    from apps.projects.models import Project

    user = get_user_model().objects.create_user("schema_engine_user", password="x")
    return Project.objects.create(name="Schema Engine Test Project", created_by=user)


class TestProjectBoundFormSpec:
    def test_project_config_applied_in_form_spec(self, latest_schema, project):
        """A project-level SchemaUIConfig with globally_hidden_slots should
        hide that slot from a project-bound LoomSchemaView's form_spec(),
        with no ui config args passed in explicitly by the caller."""
        SchemaUIConfig.objects.create(
            schema_version=latest_schema,
            project=project,
            layers=[],
            ontology_routing={},
            widget_overrides={},
            globally_hidden_slots=["original_sentence"],
            slot_help_text={},
        )

        lsv = LoomSchemaView(latest_schema, project=project)
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s["name"] for layer in spec for s in layer["slots"]]

        assert "original_sentence" not in all_slots

    def test_no_project_falls_back_to_ungated_spec(self, latest_schema):
        """Without a project bound, form_spec() keeps its old unlayered,
        nothing-hidden default — no SchemaUIConfig lookup happens."""
        lsv = LoomSchemaView(latest_schema)
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s["name"] for layer in spec for s in layer["slots"]]

        assert "original_sentence" in all_slots
