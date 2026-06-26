"""
Phase 2 tests: schema loading, form-spec generation, schema switching.

Run with: pytest tests/test_schemas.py
DB tests require a running Postgres: docker compose up -d db
"""

import pytest

from apps.schemas.models import SchemaVersion
from apps.schemas.schema_engine import LoomSchemaView, get_schema_view, invalidate_cache

CAMO_040 = "config/schema/camo-0.4.0.yaml"
CAMO_050 = "config/schema/camo-0.5.0.yaml"


# ── Pure-Python engine tests (no database required) ───────────────────────────


class _StubSchemaVersion:
    """Minimal stand-in so LoomSchemaView can be instantiated without a DB."""

    def __init__(self, yaml_path: str, version: str = "0.4.0"):
        with open(yaml_path) as f:
            self.linkml_yaml = f.read()
        self.version = version
        self.pk = -1  # sentinel — not stored in DB


class TestEngineNoDB:
    """Fast tests against real YAML; no Postgres needed."""

    def test_class_names(self):
        lsv = LoomSchemaView(_StubSchemaVersion(CAMO_040))
        assert "CausalEdge" in lsv.class_names()
        assert "CausalNode" in lsv.class_names()

    def test_enum_names(self):
        lsv = LoomSchemaView(_StubSchemaVersion(CAMO_040))
        assert "ClaimStrengthEnum" in lsv.enum_names()

    def test_form_spec_layers_structure(self):
        import yaml

        with open("config/loom_ui.yaml") as f:
            ui = yaml.safe_load(f)
        lsv = LoomSchemaView(_StubSchemaVersion(CAMO_040))
        spec = lsv.form_spec(
            "CausalEdge",
            ui_layers=ui["layers"],
            ontology_routing=ui.get("ontology_routing", {}),
        )
        layer_ids = [s["id"] for s in spec]
        assert "layer1" in layer_ids
        assert "layer4" in layer_ids

    def test_claim_strength_is_select_with_choices(self):
        lsv = LoomSchemaView(_StubSchemaVersion(CAMO_040))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        cs = next(s for s in all_slots if s["name"] == "claim_strength")
        assert cs["widget"] == "select"
        assert len(cs["choices"]) > 0

    def test_linguistic_cues_present(self):
        lsv = LoomSchemaView(_StubSchemaVersion(CAMO_040))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        cs = next(s for s in all_slots if s["name"] == "claim_strength")
        cues = [c["linguistic_cues"] for c in cs["choices"] if c["linguistic_cues"]]
        assert len(cues) > 0

    def test_subject_is_node_picker(self):
        lsv = LoomSchemaView(_StubSchemaVersion(CAMO_040))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        subj = next(s for s in all_slots if s["name"] == "subject")
        assert subj["widget"] == "node_picker"

    def test_mediation_is_fieldset(self):
        lsv = LoomSchemaView(_StubSchemaVersion(CAMO_040))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        med = next(s for s in all_slots if s["name"] == "mediation")
        assert med["widget"] == "fieldset"

    def test_v050_adds_biotic_interaction_type_no_db(self):
        lsv = LoomSchemaView(_StubSchemaVersion(CAMO_050, "0.5.0"))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        names = [s["name"] for s in all_slots]
        assert "biotic_interaction_type" in names

    def test_v050_adds_hypothesis_record_no_db(self):
        lsv = LoomSchemaView(_StubSchemaVersion(CAMO_050, "0.5.0"))
        assert "HypothesisRecord" in lsv.class_names()

    def test_v040_missing_biotic_interaction_type_no_db(self):
        lsv = LoomSchemaView(_StubSchemaVersion(CAMO_040))
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        names = [s["name"] for s in all_slots]
        assert "biotic_interaction_type" not in names


def _load_yaml(path: str) -> str:
    with open(path) as f:
        return f.read()


@pytest.fixture
def schema_040(db):
    sv = SchemaVersion.objects.create(
        version="0.4.0",
        linkml_yaml=_load_yaml(CAMO_040),
        is_active=True,
    )
    yield sv
    invalidate_cache(sv.pk)


@pytest.fixture
def schema_050(db):
    sv = SchemaVersion.objects.create(
        version="0.5.0",
        linkml_yaml=_load_yaml(CAMO_050),
        is_active=True,
    )
    yield sv
    invalidate_cache(sv.pk)


# ── SchemaVersion model ───────────────────────────────────────────────────────


class TestSchemaVersionModel:
    def test_sha256_computed_on_save(self, schema_040):
        assert len(schema_040.sha256) == 64

    def test_get_active_returns_active(self, schema_040):
        active = SchemaVersion.get_active()
        assert active is not None
        assert active.version == "0.4.0"

    def test_only_one_active(self, db):
        sv1 = SchemaVersion.objects.create(
            version="0.3.0", linkml_yaml=_load_yaml(CAMO_040), is_active=True
        )
        sv2 = SchemaVersion.objects.create(
            version="0.4.0", linkml_yaml=_load_yaml(CAMO_040), is_active=True
        )
        # sv1 should have been deactivated when sv2 was saved
        sv1.refresh_from_db()
        assert not sv1.is_active
        assert sv2.is_active
        invalidate_cache()


# ── Schema engine / form spec ─────────────────────────────────────────────────


class TestSchemaEngine:
    def test_class_names_includes_causal_edge(self, schema_040):
        lsv = get_schema_view(schema_040)
        assert "CausalEdge" in lsv.class_names()

    def test_enum_names_includes_claim_strength(self, schema_040):
        lsv = get_schema_view(schema_040)
        assert "ClaimStrengthEnum" in lsv.enum_names()

    def test_form_spec_returns_layers(self, schema_040):
        lsv = get_schema_view(schema_040)
        spec = lsv.form_spec("CausalEdge")
        assert isinstance(spec, list)
        assert len(spec) >= 1

    def test_form_spec_with_ui_layers(self, schema_040):
        import yaml

        with open("config/loom_ui.yaml") as f:
            ui = yaml.safe_load(f)
        lsv = get_schema_view(schema_040)
        spec = lsv.form_spec(
            "CausalEdge",
            ui_layers=ui["layers"],
            ontology_routing=ui.get("ontology_routing", {}),
        )
        layer_ids = [s["id"] for s in spec]
        assert "layer1" in layer_ids
        assert "layer4" in layer_ids

    def test_claim_strength_slot_is_select(self, schema_040):
        lsv = get_schema_view(schema_040)
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        cs = next((s for s in all_slots if s["name"] == "claim_strength"), None)
        assert cs is not None
        assert cs["widget"] == "select"
        assert len(cs["choices"]) > 0

    def test_claim_strength_choices_have_linguistic_cues(self, schema_040):
        lsv = get_schema_view(schema_040)
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        cs = next(s for s in all_slots if s["name"] == "claim_strength")
        # At least one choice should have non-empty linguistic_cues
        cues = [c["linguistic_cues"] for c in cs["choices"] if c["linguistic_cues"]]
        assert len(cues) > 0

    def test_subject_slot_is_node_picker(self, schema_040):
        lsv = get_schema_view(schema_040)
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        subj = next((s for s in all_slots if s["name"] == "subject"), None)
        assert subj is not None
        assert subj["widget"] == "node_picker"

    def test_mediation_is_fieldset(self, schema_040):
        lsv = get_schema_view(schema_040)
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        med = next((s for s in all_slots if s["name"] == "mediation"), None)
        assert med is not None
        assert med["widget"] == "fieldset"

    def test_causal_node_form_spec(self, schema_040):
        lsv = get_schema_view(schema_040)
        spec = lsv.form_spec("CausalNode")
        all_slots = [s for layer in spec for s in layer["slots"]]
        names = [s["name"] for s in all_slots]
        assert "entity_type" in names
        assert "name" in names


# ── Schema switching (Phase 2 acceptance criterion) ───────────────────────────


class TestSchemaSwitching:
    def test_v050_adds_biotic_interaction_type(self, schema_050):
        """Switching to v0.5 must surface biotic_interaction_type with no code change."""
        lsv = get_schema_view(schema_050)
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        names = [s["name"] for s in all_slots]
        assert "biotic_interaction_type" in names

    def test_v050_adds_hypothesis_record_class(self, schema_050):
        lsv = get_schema_view(schema_050)
        assert "HypothesisRecord" in lsv.class_names()

    def test_v040_does_not_have_biotic_interaction_type(self, schema_040):
        lsv = get_schema_view(schema_040)
        spec = lsv.form_spec("CausalEdge")
        all_slots = [s for layer in spec for s in layer["slots"]]
        names = [s["name"] for s in all_slots]
        assert "biotic_interaction_type" not in names

    def test_cache_is_per_schema_version(self, db):
        """Each version gets its own cache slot."""
        sv1 = SchemaVersion.objects.create(
            version="0.4.0-a", linkml_yaml=_load_yaml(CAMO_040), is_active=False
        )
        sv2 = SchemaVersion.objects.create(
            version="0.5.0-a", linkml_yaml=_load_yaml(CAMO_050), is_active=True
        )
        lsv1 = get_schema_view(sv1)
        lsv2 = get_schema_view(sv2)
        assert lsv1 is not lsv2
        assert lsv1.version == "0.4.0-a"
        assert lsv2.version == "0.5.0-a"
        invalidate_cache()


# ── Annotation models + service layer ────────────────────────────────────────


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
    def test_create_graph_node_edge(self, schema_040, annotator, project_with_doc):
        from apps.annotation.services import create_edge, create_graph, create_node

        proj, doc = project_with_doc
        graph = create_graph(doc, annotator, schema_040)
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

    def test_advance_edge_status(self, schema_040, annotator, project_with_doc):
        from apps.annotation.services import advance_edge_status, create_edge, create_graph, create_node

        proj, doc = project_with_doc
        graph = create_graph(doc, annotator, schema_040)
        na = create_node(graph, {"name": "A"})
        nb = create_node(graph, {"name": "B"})
        edge = create_edge(graph, na, nb, {})
        assert edge.status == "draft"

        edge = advance_edge_status(edge, annotator)
        assert edge.status == "complete"

    def test_node_data_stored_as_jsonb(self, schema_040, annotator, project_with_doc):
        from apps.annotation.models import Node
        from apps.annotation.services import create_graph, create_node

        proj, doc = project_with_doc
        graph = create_graph(doc, annotator, schema_040)
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
