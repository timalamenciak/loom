"""
Phase 6 tests: serializer helpers, renderer logic, and DB-backed export.

Pure-Python tests (no DB) cover _clean(), type casting, and renderers.
DB tests cover the full serialize_graph() → provenance → YAML pipeline.
"""

from pathlib import Path

import pytest

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "config" / "schema" / "camo-0.4.0.yaml"


def _schema_yaml() -> str:
    if not SCHEMA_PATH.exists():
        pytest.skip("CAMO schema not found")
    return SCHEMA_PATH.read_text(encoding="utf-8")


# ── Pure-Python: _clean() ────────────────────────────────────────────────────


class TestCleanDict:
    def test_strips_empty_string(self):
        from apps.export.serializer import _clean
        assert _clean({"a": "", "b": "val"}) == {"b": "val"}

    def test_strips_none(self):
        from apps.export.serializer import _clean
        assert _clean({"a": None, "b": "val"}) == {"b": "val"}

    def test_casts_n_observations_to_int(self):
        from apps.export.serializer import _clean
        assert _clean({"n_observations": "45"}) == {"n_observations": 45}

    def test_casts_certainty_grade_to_float(self):
        from apps.export.serializer import _clean
        assert _clean({"certainty_grade": "0.8"}) == {"certainty_grade": 0.8}

    def test_strips_empty_nested_dict(self):
        from apps.export.serializer import _clean
        assert _clean({"mediation": {"has_mediator": ""}}) == {}

    def test_keeps_non_empty_nested(self):
        from apps.export.serializer import _clean
        result = _clean({"mediation": {"has_mediator": "yes", "mediator_notes": ""}})
        assert result == {"mediation": {"has_mediator": "yes"}}

    def test_strips_empty_list_items(self):
        from apps.export.serializer import _clean
        assert _clean({"part_qualifiers": ["", None, "PATO:001"]}) == {
            "part_qualifiers": ["PATO:001"]
        }

    def test_removes_empty_list(self):
        from apps.export.serializer import _clean
        assert _clean({"part_qualifiers": ["", None]}) == {}


# ── Pure-Python: renderers ───────────────────────────────────────────────────


class TestRosettaRenderer:
    def test_basic_statement(self):
        from apps.export.renderers import render_rosetta
        data = {
            "nodes": [
                {"node_id": "n1", "name": "Buckthorn"},
                {"node_id": "n2", "name": "Soil N"},
            ],
            "edges": [
                {"edge_id": "e1", "subject": "n1", "object": "n2",
                 "predicate": "positively_regulates"},
            ],
        }
        results = render_rosetta(data, _schema_yaml())
        assert len(results) == 1
        assert "Buckthorn" in results[0].statement
        assert "Soil N" in results[0].statement
        assert "increases" in results[0].statement

    def test_hedged_when_certainty_below_half(self):
        from apps.export.renderers import render_rosetta
        data = {
            "nodes": [{"node_id": "n1", "name": "A"}, {"node_id": "n2", "name": "B"}],
            "edges": [
                {"edge_id": "e1", "subject": "n1", "object": "n2",
                 "predicate": "positively_regulates", "certainty_grade": 0.3},
            ],
        }
        results = render_rosetta(data, _schema_yaml())
        assert results[0].statement.lower().startswith("possibly")

    def test_not_hedged_when_certainty_at_half(self):
        from apps.export.renderers import render_rosetta
        data = {
            "nodes": [{"node_id": "n1", "name": "A"}, {"node_id": "n2", "name": "B"}],
            "edges": [
                {"edge_id": "e1", "subject": "n1", "object": "n2",
                 "predicate": "positively_regulates", "certainty_grade": 0.5},
            ],
        }
        results = render_rosetta(data, _schema_yaml())
        assert not results[0].statement.lower().startswith("possibly")

    def test_unknown_predicate_excluded(self):
        from apps.export.renderers import render_rosetta
        data = {
            "nodes": [{"node_id": "n1", "name": "A"}, {"node_id": "n2", "name": "B"}],
            "edges": [{"edge_id": "e1", "subject": "n1", "object": "n2",
                       "predicate": "unknown_predicate"}],
        }
        assert render_rosetta(data, _schema_yaml()) == []

    def test_facilitated_by_uses_object_first(self):
        from apps.export.renderers import render_rosetta
        data = {
            "nodes": [{"node_id": "n1", "name": "Shade"}, {"node_id": "n2", "name": "Seedlings"}],
            "edges": [{"edge_id": "e1", "subject": "n1", "object": "n2",
                       "predicate": "is_facilitated_by"}],
        }
        results = render_rosetta(data, _schema_yaml())
        # template: "{object} is facilitated by {subject}"
        assert results[0].statement.startswith("Seedlings")
        assert "Shade" in results[0].statement


class TestFCMRenderer:
    def test_positive_tendency(self):
        from apps.export.renderers import render_fcm
        data = {"edges": [{"edge_id": "e1", "predicate": "positively_regulates",
                            "claim_strength": "tendency"}]}
        results = render_fcm(data, _schema_yaml())
        assert results[0].weight == 0.6
        assert results[0].sign == 1

    def test_negative_strong_tendency(self):
        from apps.export.renderers import render_fcm
        data = {"edges": [{"edge_id": "e1", "predicate": "negatively_regulates",
                            "claim_strength": "strong_tendency"}]}
        results = render_fcm(data, _schema_yaml())
        assert results[0].weight == -0.8

    def test_unknown_strength_uses_default(self):
        from apps.export.renderers import render_fcm
        data = {"edges": [{"edge_id": "e1", "predicate": "positively_regulates",
                            "claim_strength": "not_addressed"}]}
        results = render_fcm(data, _schema_yaml())
        assert results[0].weight == 0.5

    def test_no_predicate_excluded(self):
        from apps.export.renderers import render_fcm
        data = {"edges": [{"edge_id": "e1"}]}
        assert render_fcm(data, _schema_yaml()) == []


# ── DB fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def export_user(db):
    from django.contrib.auth import get_user_model

    from apps.projects.models import Project, ProjectMembership

    User = get_user_model()
    user = User.objects.create_user("exporter", password="pw")
    project = Project.objects.create(name="Export Test", created_by=user)
    ProjectMembership.objects.create(project=project, user=user, role="annotator")
    return user, project


@pytest.fixture
def schema_version(db):
    from apps.schemas.models import SchemaVersion
    if not SCHEMA_PATH.exists():
        pytest.skip("CAMO schema not found")
    return SchemaVersion.objects.create(
        version="0.4.0",
        linkml_yaml=SCHEMA_PATH.read_text(encoding="utf-8"),
        is_active=True,
    )


@pytest.fixture
def populated_graph(export_user, schema_version):
    from apps.annotation.models import CausalGraph, Edge, Node
    from apps.projects.models import Document

    user, project = export_user
    doc = Document.objects.create(
        project=project,
        source="manual",
        title="Buckthorn drives N cycling",
        authors=["Smith, J.", "Jones, K."],
        year=2023,
        doi="10.9999/test",
        journal="J. Ecology",
        canonical_text="Rhamnus cathartica increases soil nitrogen.",
    )
    graph = CausalGraph.objects.create(
        document=doc, annotator=user, schema_version=schema_version
    )
    node_a = Node.objects.create(
        graph=graph, node_id="node-a", name="Buckthorn",
        data={"entity_type": "biotic", "entity_term": "NCBITaxon:712036", "direction": "increases"},
        schema_version=schema_version,
    )
    node_b = Node.objects.create(
        graph=graph, node_id="node-b", name="Soil nitrogen",
        data={"entity_type": "abiotic", "direction": "increases"},
        schema_version=schema_version,
    )
    Edge.objects.create(
        graph=graph, edge_id="edge-1",
        subject=node_a, object=node_b,
        predicate="positively_regulates",
        claim_strength="tendency",
        data={
            "original_sentence": "Rhamnus cathartica increases soil nitrogen.",
            "certainty_grade": "0.8",
            "evidential_basis": {
                "study_design": "observational",
                "n_observations": "12",
            },
        },
        schema_version=schema_version,
    )
    return graph


# ── DB: serializer ───────────────────────────────────────────────────────────


class TestSerializeGraph:
    def test_top_level_keys(self, populated_graph):
        from apps.export.serializer import serialize_graph
        data = serialize_graph(populated_graph)
        assert {"graph_id", "source_document", "nodes", "edges"} <= set(data)

    def test_node_count_and_ids(self, populated_graph):
        from apps.export.serializer import serialize_graph
        data = serialize_graph(populated_graph)
        assert len(data["nodes"]) == 2
        ids = {n["node_id"] for n in data["nodes"]}
        assert ids == {"node-a", "node-b"}

    def test_node_fields(self, populated_graph):
        from apps.export.serializer import serialize_graph
        data = serialize_graph(populated_graph)
        node = next(n for n in data["nodes"] if n["node_id"] == "node-a")
        assert node["name"] == "Buckthorn"
        assert node["entity_type"] == "biotic"

    def test_edge_subject_object_are_node_ids(self, populated_graph):
        from apps.export.serializer import serialize_graph
        data = serialize_graph(populated_graph)
        edge = data["edges"][0]
        assert edge["subject"] == "node-a"
        assert edge["object"] == "node-b"

    def test_promoted_columns_win(self, populated_graph):
        from apps.export.serializer import serialize_graph
        data = serialize_graph(populated_graph)
        edge = data["edges"][0]
        assert edge["predicate"] == "positively_regulates"
        assert edge["claim_strength"] == "tendency"

    def test_numeric_casting(self, populated_graph):
        from apps.export.serializer import serialize_graph
        data = serialize_graph(populated_graph)
        edge = data["edges"][0]
        assert edge["certainty_grade"] == 0.8
        assert edge["evidential_basis"]["n_observations"] == 12

    def test_source_document(self, populated_graph):
        from apps.export.serializer import serialize_graph
        data = serialize_graph(populated_graph)
        sd = data["source_document"]
        assert sd["doc_title"] == "Buckthorn drives N cycling"
        assert sd["doc_year"] == 2023
        assert "Smith, J." in sd["doc_authors"]
        assert sd["doc_doi"] == "10.9999/test"


class TestBuildProvenance:
    def test_sha256_is_64_hex_chars(self, populated_graph):
        import yaml

        from apps.export.serializer import build_provenance, serialize_graph
        data = serialize_graph(populated_graph)
        pre_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=True)
        prov = build_provenance(populated_graph, pre_yaml.encode())
        assert len(prov["export_sha256"]) == 64
        assert all(c in "0123456789abcdef" for c in prov["export_sha256"])

    def test_schema_version_matches(self, populated_graph):
        import yaml

        from apps.export.serializer import build_provenance, serialize_graph
        data = serialize_graph(populated_graph)
        pre_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=True)
        prov = build_provenance(populated_graph, pre_yaml.encode())
        assert prov["schema_version_str"] == "0.4.0"
        assert prov["exporter_version"] == "loom-0.1.0"

    def test_sha256_is_deterministic(self, populated_graph):
        import yaml

        from apps.export.serializer import build_provenance, serialize_graph
        data = serialize_graph(populated_graph)
        pre_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=True)
        p1 = build_provenance(populated_graph, pre_yaml.encode())
        p2 = build_provenance(populated_graph, pre_yaml.encode())
        assert p1["export_sha256"] == p2["export_sha256"]


# ── DB: export view ──────────────────────────────────────────────────────────


class TestExportGraphView:
    def test_returns_200(self, populated_graph, export_user):
        from django.test import Client
        user, _ = export_user
        client = Client()
        client.login(username="exporter", password="pw")
        resp = client.get(f"/export/graphs/{populated_graph.pk}/")
        assert resp.status_code == 200

    def test_download_returns_yaml(self, populated_graph, export_user):
        from django.test import Client
        user, _ = export_user
        client = Client()
        client.login(username="exporter", password="pw")
        resp = client.get(f"/export/graphs/{populated_graph.pk}/?download=1")
        assert resp.status_code == 200
        assert "yaml" in resp["Content-Type"]
        assert b"graph_id:" in resp.content

    def test_yaml_contains_nodes_and_edges(self, populated_graph, export_user):
        import yaml
        from django.test import Client
        user, _ = export_user
        client = Client()
        client.login(username="exporter", password="pw")
        resp = client.get(f"/export/graphs/{populated_graph.pk}/?download=1")
        data = yaml.safe_load(resp.content)
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert "provenance" in data
        assert "export_sha256" in data["provenance"]

    def test_requires_login(self, populated_graph):
        from django.test import Client
        resp = Client().get(f"/export/graphs/{populated_graph.pk}/")
        assert resp.status_code == 302
        assert "/accounts/login/" in resp["Location"]
