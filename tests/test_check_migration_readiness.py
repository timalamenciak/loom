"""Tests for scripts/check_migration_readiness.py.

Imported as a module (its Django bootstrap is a no-op under pytest-django,
which has already called django.setup()) so these checks can be exercised
directly without shelling out to a subprocess.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from apps.annotation.models import CausalGraph, Edge, Node
from apps.annotation.services import create_edge, create_graph, create_node
from apps.ontology.models import OntologySnapshot
from apps.projects.models import Document, Project

pytestmark = pytest.mark.django_db


def _load_script():
    """Import scripts/check_migration_readiness.py as a module.

    It's not a package (scripts/ has no __init__.py, by design — it's a
    collection of standalone entry points, not an importable library), so it
    can't be reached with a normal dotted import; load it from its file path
    instead.
    """
    path = (
        Path(__file__).resolve().parent.parent
        / "scripts"
        / "check_migration_readiness.py"
    )
    spec = importlib.util.spec_from_file_location("check_migration_readiness", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        "readiness-admin", "readiness-admin@test.example", "password"
    )


@pytest.fixture
def project(admin_user, latest_schema):
    p = Project.objects.create(name="Readiness Test Project", created_by=admin_user)
    p.active_schema = latest_schema
    p.save(update_fields=["active_schema"])
    return p


@pytest.fixture
def document(project):
    return Document.objects.create(
        project=project,
        source=Document.SOURCE_MANUAL,
        title="Readiness Doc",
        canonical_text="Wolves reduce deer populations.",
    )


def _make_valid_camo_graph(document, admin_user, schema_version):
    """Build a graph that actually passes validate_graph() against a real
    CAMO schema.

    Two deliberate departures from the rest of this file's fixtures, both
    forced by the same underlying gap (see docs/migration-v0-to-v1.md's note
    on the serializer/schema mismatch found while building
    tests/e2e/test_full_annotation_workflow.py):

    - Pinned to frozen_schema_040, like tests/test_export.py's own
      populated_graph fixture, not latest_schema — the *current* CAMO schema
      doesn't declare a few keys apps/export/serializer.py always emits
      (source_document at the graph level, among others), so no data set
      validates against it. Using latest_schema here would fail this test
      for a reason unrelated to what it's checking.
    - Nodes/edges are created directly via the ORM, not
      apps.annotation.services.create_node/create_edge — those service
      functions tag every payload with an "annotator" key
      (_annotate_with_orcid), which even CAMO 0.4.0 doesn't declare either.
      populated_graph makes the same choice for the same reason.
    """
    from apps.annotation.models import CausalGraph, Edge, Node

    graph = CausalGraph.objects.create(
        document=document, annotator=admin_user, schema_version=schema_version
    )
    subject = Node.objects.create(
        graph=graph,
        node_id="node-subject",
        name="Wolves",
        data={
            "entity_type": "biotic",
            "entity_term": "WD:Q712036",
            "direction": "increases",
        },
        schema_version=schema_version,
    )
    obj = Node.objects.create(
        graph=graph,
        node_id="node-object",
        name="Deer",
        data={"entity_type": "abiotic", "direction": "increases"},
        schema_version=schema_version,
    )
    Edge.objects.create(
        graph=graph,
        edge_id="edge-1",
        subject=subject,
        object=obj,
        predicate="positively_regulates",
        claim_strength="tendency",
        data={
            "original_sentence": "Wolves reduce deer populations.",
            "certainty_grade": "0.8",
        },
        schema_version=schema_version,
    )
    return graph


class TestCheckActiveSchema:
    def test_fails_with_no_active_schema(self, script, db):
        from apps.schemas.models import SchemaVersion

        SchemaVersion.objects.update(is_active=False)
        assert script.check_active_schema() != []

    def test_passes_with_active_schema(self, script, latest_schema):
        assert script.check_active_schema() == []


class TestCheckOntologySnapshot:
    def test_fails_with_no_snapshot(self, script, db):
        assert script.check_ontology_snapshot() != []

    def test_passes_with_a_snapshot(self, script, db):
        OntologySnapshot.objects.create(name="test-snapshot")
        assert script.check_ontology_snapshot() == []


class TestCheckNoOrphanedSchemaVersion:
    def test_passes_when_every_graph_has_a_schema_version(
        self, script, document, admin_user, latest_schema
    ):
        graph = create_graph(document, admin_user, latest_schema)
        subject = create_node(graph, {"name": "Wolves"}, actor=admin_user)
        obj = create_node(graph, {"name": "Deer"}, actor=admin_user)
        create_edge(graph, subject, obj, {}, actor=admin_user)

        assert script.check_no_orphaned_schema_version() == []
        assert Node.objects.filter(graph__schema_version__isnull=True).count() == 0
        assert Edge.objects.filter(graph__schema_version__isnull=True).count() == 0


class TestCheckGraphsExportCleanly:
    def test_passes_with_no_graphs(self, script, db):
        assert CausalGraph.objects.count() == 0
        assert script.check_graphs_export_cleanly() == []

    def test_passes_for_a_valid_graph(
        self, script, document, admin_user, frozen_schema_040
    ):
        _make_valid_camo_graph(document, admin_user, frozen_schema_040)

        assert script.check_graphs_export_cleanly() == []

    def test_fails_for_an_invalid_graph(
        self, script, document, admin_user, latest_schema, monkeypatch
    ):
        graph = create_graph(document, admin_user, latest_schema)
        monkeypatch.setattr(
            script,
            "validate_graph",
            lambda g: (False, ["Additional properties are not allowed"]),
        )

        errors = script.check_graphs_export_cleanly()
        assert errors
        assert any(str(graph.pk) in line for line in errors)


class TestMainExitCode:
    def test_main_returns_0_when_everything_is_ready(
        self, script, document, admin_user, latest_schema, frozen_schema_040
    ):
        # latest_schema satisfies "an active schema exists"; the graph itself
        # is pinned to frozen_schema_040 so it actually passes export
        # validation — see _make_valid_camo_graph's docstring.
        OntologySnapshot.objects.create(name="test-snapshot")
        _make_valid_camo_graph(document, admin_user, frozen_schema_040)

        assert script.main() == 0

    def test_main_returns_1_when_a_check_fails(self, script, db):
        from apps.schemas.models import SchemaVersion

        SchemaVersion.objects.update(is_active=False)
        assert script.main() == 1
