"""Phase 2 tests: schema loading, form-spec generation, schema switching.

Run with: pytest tests/test_schemas.py
DB tests require a running Postgres: docker compose up -d db

Most tests here exercise engine *mechanics* (slot/class discovery, widget
selection rules, layer assignment) against `latest_schema` / `latest_schema_yaml`
so they keep tracking whatever CAMO looks like today instead of a frozen old
snapshot. A few tests are deliberately pinned to a specific historical version
because they cover a structural/annotation pattern (or a since-removed
feature) that only exists in that version — each of those says why in a
comment. See tests/schema_fixtures.py and conftest.py for the fixtures.
"""

import pytest

from apps.schemas.models import SchemaVersion
from apps.schemas.schema_engine import LoomSchemaView, get_schema_view, invalidate_cache

CAMO_041 = "config/schema/camo-0.4.1.yaml"
CAMO_042 = "config/schema/camo-0.4.2.yaml"


# ── Pure-Python engine tests (no database required) ───────────────────────────


class _StubSchemaVersion:
    """Minimal stand-in so LoomSchemaView can be instantiated without a DB."""

    def __init__(self, yaml_text: str, version: str = "stub"):
        self.linkml_yaml = yaml_text
        self.version = version
        self.pk = -1  # sentinel — not stored in DB

    @classmethod
    def from_path(cls, yaml_path: str, version: str = "stub") -> "_StubSchemaVersion":
        with open(yaml_path) as f:
            return cls(f.read(), version)


class TestEngineNoDB:
    """Fast tests against the current schema on disk; no Postgres needed."""

    def test_class_names(self, latest_schema_yaml):
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        assert "CausalEdge" in lsv.class_names()
        assert "CausalNode" in lsv.class_names()

    def test_enum_names(self, latest_schema_yaml):
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        assert "ClaimStrengthEnum" in lsv.enum_names()

    def test_form_spec_layers_structure(self, latest_schema_yaml):
        import yaml

        with open("config/loom_ui.yaml") as f:
            ui = yaml.safe_load(f)
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        spec = lsv.form_spec(
            "CausalEdge",
            ui_layers=ui["layers"],
            ontology_routing=ui.get("ontology_routing", {}),
        )
        layer_ids = [s["id"] for s in spec]
        assert "layer1" in layer_ids
        assert "layer4" in layer_ids

    def test_widget_overrides_come_from_sidecar_configuration(self, latest_schema_yaml):
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        spec = lsv.form_spec(
            "CausalEdge", widget_overrides={"original_sentence": "textarea"}
        )
        slots = {slot["name"]: slot for layer in spec for slot in layer["slots"]}
        assert slots["original_sentence"]["widget"] == "textarea"

    def test_ontology_prefixes_come_from_schema_annotations(self):
        schema = """
id: https://example.org/ontology-routing
name: ontology-routing
imports: [linkml:types]
classes:
  Example:
    attributes:
      term:
        range: uriorcurie
        annotations:
          loom_ontologies: "NCBITaxon, ENVO"
"""
        stub = type("StubSchemaVersion", (), {"linkml_yaml": schema, "version": "x"})()
        lsv = LoomSchemaView(stub)

        spec = lsv.form_spec("Example", ontology_routing={"term": ["PATO"]})
        slots = {slot["name"]: slot for layer in spec for slot in layer["slots"]}

        assert slots["term"]["widget"] == "ontology_autocomplete"
        assert slots["term"]["ontology_prefixes"] == ["NCBITaxon", "ENVO"]

    def test_ontology_prefixes_fall_back_to_sidecar_routing(self):
        schema = """
id: https://example.org/ontology-routing
name: ontology-routing
imports: [linkml:types]
classes:
  Example:
    attributes:
      term:
        range: uriorcurie
"""
        stub = type("StubSchemaVersion", (), {"linkml_yaml": schema, "version": "x"})()
        lsv = LoomSchemaView(stub)

        spec = lsv.form_spec("Example", ontology_routing={"term": ["PATO"]})
        slots = {slot["name"]: slot for layer in spec for slot in layer["slots"]}

        assert slots["term"]["ontology_prefixes"] == ["PATO"]

    def test_camo_042_entity_term_uses_schema_ontology_annotations(self):
        """Pinned to 0.4.2 deliberately.

        0.4.2 is the last version where `entity_term` carried an embedded
        `loom_ontologies` schema annotation; later versions moved ontology
        routing for this slot to the loom_ui.yaml sidecar instead. This test
        covers the schema-annotation code path specifically, not "whatever
        CAMO looks like today" — do not repoint it at latest_schema.
        """
        lsv = LoomSchemaView(_StubSchemaVersion.from_path(CAMO_042, "0.4.2"))
        spec = lsv.form_spec(
            "CausalNode",
            ontology_routing={"entity_term": ["NCBITaxon", "ENVO"]},
        )
        slots = {slot["name"]: slot for layer in spec for slot in layer["slots"]}

        assert slots["entity_term"]["ontology_prefixes"] == [
            "NCBITaxon",
            "CHEBI",
            "ENVO",
            "GO",
            "PATO",
        ]

    def test_claim_strength_is_select_with_choices(self, latest_schema_yaml):
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        cs = next(s for s in all_slots if s["name"] == "claim_strength")
        assert cs["widget"] == "select"
        assert len(cs["choices"]) > 0

    def test_linguistic_cues_present(self, latest_schema_yaml):
        """`linguistic_cues` falls back to `exemplars` in `_enum_choices` —
        different CAMO enums use different annotation names for the same
        UI hint (ClaimStrengthEnum uses `exemplars`, PhilosophicalAccountEnum
        uses `linguistic_cues`), so this must hold regardless of which one
        the current schema's ClaimStrengthEnum happens to use."""
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        cs = next(s for s in all_slots if s["name"] == "claim_strength")
        cues = [c["linguistic_cues"] for c in cs["choices"] if c["linguistic_cues"]]
        assert len(cues) > 0

    def test_subject_is_node_picker(self, latest_schema_yaml):
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        subj = next(s for s in all_slots if s["name"] == "subject")
        assert subj["widget"] == "node_picker"

    def test_mediation_is_fieldset(self, latest_schema_yaml):
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        med = next(s for s in all_slots if s["name"] == "mediation")
        assert med["widget"] == "fieldset"

    def test_large_enum_gets_enum_autocomplete_widget(self, latest_schema_yaml):
        """Any enum slot with more than the large-enum threshold worth of
        choices should get enum_autocomplete — the rule, not a fact about
        which specific enum happens to be large in any one CAMO version."""
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        large_enum_slots = [
            s for s in all_slots if s.get("choices") and len(s["choices"]) > 20
        ]
        assert large_enum_slots, "expected at least one large-enum slot on CausalEdge"
        for slot in large_enum_slots:
            assert slot["widget"] == "enum_autocomplete"

    def test_source_document_study_ecosystem_uses_large_enum_autocomplete(self):
        """Pinned to 0.4.2 deliberately.

        SourceDocument.study_ecosystem was removed in 0.6.0 (see causalmosaic
        CHANGELOG). This test intentionally exercises the removed feature as
        a historical regression case — it must stay on 0.4.2.
        """
        lsv = LoomSchemaView(_StubSchemaVersion.from_path(CAMO_042, "0.4.2"))
        spec = lsv.form_spec("SourceDocument")
        all_slots = [s for layer in spec for s in layer["slots"]]
        eco = next((s for s in all_slots if s["name"] == "study_ecosystem"), None)
        assert eco is not None, "study_ecosystem slot not found in SourceDocument spec"
        assert eco["widget"] == "enum_autocomplete"
        assert len(eco["choices"]) == 110
        assert any(
            choice["value"] == "temperate_subhumid_grasslands"
            and choice["label"] == "T4.5 Temperate subhumid grasslands"
            for choice in eco["choices"]
        )

    def test_enum_autocomplete_choices_use_display_label(self, latest_schema_yaml):
        """Choices for a large ontology-coded enum should use the schema's
        display_label annotation (e.g. IUCN GET codes on
        EcosystemFunctionalGroupEnum), whichever slot on CausalEdge carries
        that enum in the current schema."""
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        large_enum_slots = [
            s for s in all_slots if s.get("choices") and len(s["choices"]) > 20
        ]
        assert large_enum_slots
        first = large_enum_slots[0]["choices"][0]
        assert first["label"].startswith(
            "T"
        ), f"Expected label starting with IUCN code, got: {first['label']!r}"

    def test_small_enum_stays_as_select(self, latest_schema_yaml):
        """Any enum slot at or under the threshold should stay a plain select."""
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        small_enum_slots = [
            s for s in all_slots if s.get("choices") and 0 < len(s["choices"]) <= 20
        ]
        assert small_enum_slots
        for slot in small_enum_slots:
            assert slot["widget"] == "select"

    def test_inline_attributes_render_as_node_and_edge_inputs(self, latest_schema_yaml):
        """CAMO declares fields as inline class attributes rather than slot
        lists; verify the engine resolves both node and edge forms from
        that style against the current schema."""
        from types import SimpleNamespace

        import yaml
        from django.template.loader import render_to_string

        with open("config/loom_ui.yaml") as f:
            ui = yaml.safe_load(f)
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))
        common = {
            "project": SimpleNamespace(pk=1),
            "document": SimpleNamespace(pk=2),
            "graph": SimpleNamespace(pk=3),
            "current_data": {},
        }

        node_html = render_to_string(
            "annotation/partials/node_form.html",
            {
                **common,
                "node": None,
                "node_spec": lsv.form_spec(
                    "CausalNode",
                    ontology_routing=ui.get("ontology_routing", {}),
                ),
                "graph_nodes": [],
            },
        )
        assert 'name="name"' in node_html
        assert 'name="entity_type"' in node_html

        graph_nodes = [
            SimpleNamespace(node_id="n1", name="Cause", category=""),
            SimpleNamespace(node_id="n2", name="Effect", category=""),
        ]
        edge_html = render_to_string(
            "annotation/partials/edge_form.html",
            {
                **common,
                "edge": None,
                "edge_spec": lsv.form_spec(
                    "CausalEdge",
                    ui_layers=ui.get("layers"),
                    ontology_routing=ui.get("ontology_routing", {}),
                ),
                "graph_nodes": graph_nodes,
            },
        )
        assert 'name="subject"' in edge_html
        assert 'name="object"' in edge_html
        assert 'name="claim_strength"' in edge_html


# ── SchemaVersion model ───────────────────────────────────────────────────────


class TestSchemaVersionModel:
    def test_sha256_computed_on_save(self, latest_schema):
        assert len(latest_schema.sha256) == 64

    def test_sha256_updates_with_linkml_yaml_update_fields(self, latest_schema):
        old_digest = latest_schema.sha256
        latest_schema.linkml_yaml += "\n# revised\n"
        latest_schema.save(update_fields=["linkml_yaml"])
        latest_schema.refresh_from_db()
        assert latest_schema.sha256 != old_digest

    def test_get_active_returns_active(self, latest_schema):
        active = SchemaVersion.get_active()
        assert active is not None
        assert active.version == latest_schema.version

    def test_only_one_active(self, db, latest_schema):
        sv2 = SchemaVersion.objects.create(
            version="test-only-one-active",
            linkml_yaml=latest_schema.linkml_yaml,
            is_active=True,
        )
        # latest_schema should have been deactivated when sv2 was saved
        latest_schema.refresh_from_db()
        assert not latest_schema.is_active
        assert sv2.is_active
        invalidate_cache()


# ── Schema engine / form spec ─────────────────────────────────────────────────


class TestSchemaEngine:
    def test_class_names_includes_causal_edge(self, latest_schema):
        lsv = get_schema_view(latest_schema)
        assert "CausalEdge" in lsv.class_names()

    def test_enum_names_includes_claim_strength(self, latest_schema):
        lsv = get_schema_view(latest_schema)
        assert "ClaimStrengthEnum" in lsv.enum_names()

    def test_form_spec_returns_layers(self, latest_schema):
        lsv = get_schema_view(latest_schema)
        spec = lsv.form_spec("CausalEdge")
        assert isinstance(spec, list)
        assert len(spec) >= 1

    def test_form_spec_with_ui_layers(self, latest_schema):
        import yaml

        with open("config/loom_ui.yaml") as f:
            ui = yaml.safe_load(f)
        lsv = get_schema_view(latest_schema)
        spec = lsv.form_spec(
            "CausalEdge",
            ui_layers=ui["layers"],
            ontology_routing=ui.get("ontology_routing", {}),
        )
        layer_ids = [s["id"] for s in spec]
        assert "layer1" in layer_ids
        assert "layer4" in layer_ids

    def test_claim_strength_slot_is_select(self, latest_schema):
        lsv = get_schema_view(latest_schema)
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        cs = next((s for s in all_slots if s["name"] == "claim_strength"), None)
        assert cs is not None
        assert cs["widget"] == "select"
        assert len(cs["choices"]) > 0

    def test_subject_slot_is_node_picker(self, latest_schema):
        lsv = get_schema_view(latest_schema)
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        subj = next((s for s in all_slots if s["name"] == "subject"), None)
        assert subj is not None
        assert subj["widget"] == "node_picker"

    def test_mediation_is_fieldset(self, latest_schema):
        lsv = get_schema_view(latest_schema)
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        med = next((s for s in all_slots if s["name"] == "mediation"), None)
        assert med is not None
        assert med["widget"] == "fieldset"

    def test_causal_node_form_spec(self, latest_schema):
        lsv = get_schema_view(latest_schema)
        spec = lsv.form_spec("CausalNode")
        all_slots = [s for layer in spec for s in layer["slots"]]
        names = [s["name"] for s in all_slots]
        assert "entity_type" in names
        assert "name" in names

    def test_inline_class_attributes_generate_form_fields(self, latest_schema_yaml):
        """CAMO declares fields as attributes rather than slot lists."""
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))

        node_slots = [
            slot for layer in lsv.form_spec("CausalNode") for slot in layer["slots"]
        ]
        edge_slots = [
            slot for layer in lsv.form_spec("CausalEdge") for slot in layer["slots"]
        ]

        assert {slot["name"] for slot in node_slots} >= {"name", "entity_type"}
        assert {slot["name"] for slot in edge_slots} >= {
            "subject",
            "object",
            "claim_strength",
        }
        assert (
            next(slot for slot in edge_slots if slot["name"] == "subject")["widget"]
            == "node_picker"
        )

    def test_cached_schema_view_refreshes_when_schema_content_changes(self, db):
        old_schema = """
id: https://example.org/cache
name: cache
version: cache
classes:
  OldClass:
    attributes:
      name:
        range: string
"""
        new_schema = """
id: https://example.org/cache
name: cache
version: cache
classes:
  NewClass:
    attributes:
      name:
        range: string
"""
        schema = SchemaVersion.objects.create(
            version="cache",
            linkml_yaml=old_schema,
            is_active=True,
        )

        old_view = get_schema_view(schema)
        assert "OldClass" in old_view.class_names()

        schema.linkml_yaml = new_schema
        schema.save(update_fields=["linkml_yaml"])
        schema.refresh_from_db()
        new_view = get_schema_view(schema)

        assert new_view is not old_view
        assert "NewClass" in new_view.class_names()
        assert "OldClass" not in new_view.class_names()


# ── Schema switching (Phase 2 acceptance criterion) ───────────────────────────


class TestSchemaSwitching:
    def test_cache_is_per_schema_version(self, oldest_schema, latest_schema):
        """Each version gets its own cache slot."""
        lsv1 = get_schema_view(oldest_schema)
        lsv2 = get_schema_view(latest_schema)
        assert lsv1 is not lsv2
        assert lsv1.version == oldest_schema.version
        assert lsv2.version == latest_schema.version


class TestSchemaInputBinding:
    def test_rejects_unknown_slot(self, frozen_schema_040):
        result = get_schema_view(frozen_schema_040).bind_form_data(
            "CausalNode", {"invented_slot": "value"}
        )

        assert not result.is_valid
        assert "invented_slot" in result.errors

    def test_rejects_invalid_enum_and_preserves_value(self, frozen_schema_040):
        result = get_schema_view(frozen_schema_040).bind_form_data(
            "CausalNode", {"entity_type": "not-a-real-type"}
        )

        assert not result.is_valid
        assert result.data["entity_type"] == "not-a-real-type"
        assert "entity_type" in result.errors

    def test_coerces_nested_numbers_and_checks_bounds(self, frozen_schema_040):
        valid = get_schema_view(frozen_schema_040).bind_form_data(
            "CausalEdge",
            {
                "certainty_grade": "0.8",
                "evidential_basis__n_observations": "45",
                "evidential_basis__p_value": "0.03",
            },
            excluded_slots={"edge_id"},
        )
        invalid = get_schema_view(frozen_schema_040).bind_form_data(
            "CausalEdge",
            {"certainty_grade": "1.5"},
            excluded_slots={"edge_id"},
        )

        assert valid.is_valid
        assert valid.data["certainty_grade"] == 0.8
        assert valid.data["evidential_basis"]["n_observations"] == 45
        assert valid.data["evidential_basis"]["p_value"] == 0.03
        assert "certainty_grade" in invalid.errors

    def test_binds_multivalued_scalar_from_lines(self, frozen_schema_040):
        result = get_schema_view(frozen_schema_040).bind_form_data(
            "CausalNode",
            {"part_qualifiers": "PATO:0001\nPATO:0002\n"},
            excluded_slots={"node_id"},
        )

        assert result.is_valid
        assert result.data["part_qualifiers"] == ["PATO:0001", "PATO:0002"]

    def test_binds_indexed_multivalued_nested_class(self, frozen_schema_040):
        result = get_schema_view(frozen_schema_040).bind_form_data(
            "CausalGraph",
            {
                "graph_id": "g1",
                "nodes__0__node_id": "n1",
                "nodes__0__name": "First",
                "nodes__1__node_id": "n2",
                "nodes__1__name": "Second",
            },
        )

        assert result.is_valid
        assert [node["node_id"] for node in result.data["nodes"]] == ["n1", "n2"]

    def test_rejects_loom_managed_slot(self, frozen_schema_040):
        result = get_schema_view(frozen_schema_040).bind_form_data(
            "CausalNode",
            {"node_id": "attacker-controlled"},
            excluded_slots={"node_id"},
        )

        assert not result.is_valid
        assert "node_id" in result.errors

    def test_enforces_schema_cardinality(self):
        schema = """
id: https://example.org/cardinality
name: cardinality
imports: [linkml:types]
classes:
  Example:
    slots: [tags]
slots:
  tags:
    range: string
    multivalued: true
    minimum_cardinality: 1
    maximum_cardinality: 2
"""
        stub = type(
            "StubSchemaVersion",
            (),
            {"linkml_yaml": schema, "version": "test"},
        )()
        view = LoomSchemaView(stub)

        missing = view.bind_form_data("Example", {})
        valid = view.bind_form_data("Example", {"tags": "one\ntwo"})
        excessive = view.bind_form_data("Example", {"tags": "one\ntwo\nthree"})

        assert "tags" in missing.errors
        assert valid.is_valid
        assert valid.data["tags"] == ["one", "two"]
        assert "tags" in excessive.errors


# ── loom_ui.yaml drift guard ──────────────────────────────────────────────────


class TestUiConfigDrift:
    def test_no_drift_against_a_schema_matching_the_sidecar(self):
        from apps.schemas.ui_config import check_ui_config_drift

        schema = """
id: https://example.org/ui-drift
name: ui-drift
imports: [linkml:types]
classes:
  CausalEdge:
    attributes:
      predicate:
        range: string
"""
        stub = type("StubSchemaVersion", (), {"linkml_yaml": schema, "version": "x"})()
        lsv = LoomSchemaView(stub)
        ui_config = {"layers": [{"id": "layer1", "slots": ["predicate"]}]}

        assert check_ui_config_drift(lsv, ui_config) == []

    def test_flags_a_layer_slot_no_longer_defined_by_the_schema(self):
        from apps.schemas.ui_config import check_ui_config_drift

        schema = """
id: https://example.org/ui-drift
name: ui-drift
imports: [linkml:types]
classes:
  CausalEdge:
    attributes:
      predicate:
        range: string
"""
        stub = type("StubSchemaVersion", (), {"linkml_yaml": schema, "version": "x"})()
        lsv = LoomSchemaView(stub)
        ui_config = {
            "layers": [{"id": "layer1", "slots": ["predicate", "conditioned_by"]}]
        }

        warnings = check_ui_config_drift(lsv, ui_config)
        assert any("conditioned_by" in w for w in warnings)

    def test_current_loom_ui_yaml_against_current_schema(self, latest_schema_yaml):
        """Regression guard: this currently reports one known drift —
        `conditioned_by` was subsumed into ContextAnnotation.scope_conditions
        (see causalmosaic CHANGELOG 0.6.0->0.7.0) but loom_ui.yaml's
        layer_context still lists it. If this test's drift set ever shrinks
        to empty, tighten the assertion; if it grows, loom_ui.yaml needs
        attention (or a genuinely new slot was renamed away)."""
        import yaml

        with open("config/loom_ui.yaml") as f:
            ui_config = yaml.safe_load(f)
        lsv = LoomSchemaView(_StubSchemaVersion(latest_schema_yaml))

        from apps.schemas.ui_config import check_ui_config_drift

        warnings = check_ui_config_drift(lsv, ui_config)
        assert any("conditioned_by" in w for w in warnings), (
            "expected the known conditioned_by drift to still be flagged — "
            "update this test if loom_ui.yaml has since been fixed"
        )


# ── Annotation models + service layer ────────────────────────────────────────
#
# These use frozen_schema_040 (rather than latest_schema) because the payloads
# below use 0.4.x-era enum values (e.g. entity_type="abiotic",
# claim_strength="tendency") that are no longer valid under the current
# schema's redesigned vocabulary (EntityTypeEnum/ClaimStrengthEnum were
# replaced, not just extended, between 0.4.x and 0.7.x). Migrating these
# payloads to the current vocabulary is tracked separately — see the
# check_ui_config / vocabulary-migration follow-up.


@pytest.fixture
def annotator(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user("ann", password="x")


@pytest.fixture
def project_with_doc(db, annotator):
    from apps.projects.models import Document, Project

    proj = Project.objects.create(name="Test", created_by=annotator)
    doc = Document.objects.create(
        project=proj,
        source=Document.SOURCE_MANUAL,
        title="Sample paper",
        authors=["Author A"],
        year=2024,
    )
    return proj, doc


class TestAnnotationModels:
    def test_create_graph_node_edge(
        self, frozen_schema_040, annotator, project_with_doc
    ):
        from apps.annotation.services import create_edge, create_graph, create_node

        proj, doc = project_with_doc
        graph = create_graph(doc, annotator, frozen_schema_040)
        assert graph.pk is not None
        assert graph.status == "draft"

        node_a = create_node(graph, {"name": "Soil nitrogen", "entity_type": "abiotic"})
        node_b = create_node(graph, {"name": "Plant biomass", "entity_type": "biotic"})
        assert node_a.name == "Soil nitrogen"
        assert node_a.data["entity_type"] == "abiotic"

        edge = create_edge(
            graph,
            node_a,
            node_b,
            {"predicate": "positively_regulates", "claim_strength": "tendency"},
        )
        assert edge.predicate == "positively_regulates"
        assert edge.status == "draft"
        assert edge.data["claim_strength"] == "tendency"

    def test_advance_edge_status(self, frozen_schema_040, annotator, project_with_doc):
        from apps.annotation.services import (
            advance_edge_status,
            create_edge,
            create_graph,
            create_node,
        )

        proj, doc = project_with_doc
        graph = create_graph(doc, annotator, frozen_schema_040)
        na = create_node(graph, {"name": "A"})
        nb = create_node(graph, {"name": "B"})
        edge = create_edge(graph, na, nb, {})
        assert edge.status == "draft"

        edge = advance_edge_status(edge, annotator)
        assert edge.status == "complete"

    def test_node_data_stored_as_jsonb(
        self, frozen_schema_040, annotator, project_with_doc
    ):
        from apps.annotation.services import create_graph, create_node

        proj, doc = project_with_doc
        graph = create_graph(doc, annotator, frozen_schema_040)
        payload = {
            "name": "Predation rate",
            "entity_type": "process",
            "variable_attribute": "frequency",
            "direction": "increases",
        }
        node = create_node(graph, payload)
        node.refresh_from_db()
        assert node.data["direction"] == "increases"
        assert isinstance(node.data, dict)
