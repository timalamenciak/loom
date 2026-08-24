"""Unit tests for apps/export/graph_import.py — the format-agnostic core
that diffs uploaded Excel/YAML rows against a graph's current state and
applies an approved plan.

Pinned to CAMO 0.4.0 (frozen_schema_040) so tests can use concrete, known
slot names (evidential_basis/study_design) for the nested-fieldset
flattening coverage — see conftest.py's rationale for that fixture.
"""

import pytest

from apps.annotation.models import Edge, Node
from apps.annotation.services import create_edge, create_graph, create_node
from apps.export.graph_import import (
    VERDICT_CREATE,
    VERDICT_ERROR,
    VERDICT_NOOP,
    VERDICT_UPDATE,
    VERDICT_WOULD_DELETE,
    apply_import_plan,
    build_import_plan,
)
from apps.projects.models import Document, Project, ProjectMembership
from apps.schemas.schema_engine import get_schema_view

pytestmark = pytest.mark.django_db


@pytest.fixture
def actor(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user("importer", password="pw")


@pytest.fixture
def project(actor, frozen_schema_040):
    project = Project.objects.create(
        name="Import Test", created_by=actor, active_schema=frozen_schema_040
    )
    ProjectMembership.objects.create(project=project, user=actor, role="admin")
    return project


@pytest.fixture
def document(project):
    return Document.objects.create(
        project=project,
        source=Document.SOURCE_MANUAL,
        title="Import Test Doc",
        canonical_text="Buckthorn increases soil nitrogen.",
    )


@pytest.fixture
def graph(document, actor, frozen_schema_040):
    return create_graph(document, actor, frozen_schema_040)


@pytest.fixture
def schema_view(graph, project):
    return get_schema_view(graph.schema_version, project)


@pytest.fixture
def node_a(graph, actor):
    return create_node(
        graph,
        {"name": "Buckthorn", "entity_term": "buckthorn"},
        actor=actor,
        node_id="node-a",
    )


@pytest.fixture
def node_b(graph, actor):
    return create_node(
        graph,
        {"name": "Soil nitrogen", "entity_term": "soil-n"},
        actor=actor,
        node_id="node-b",
    )


def _plan(
    graph,
    schema_view,
    actor,
    node_rows=(),
    edge_rows=(),
    *,
    full_sync=False,
    fmt="yaml",
):
    return build_import_plan(
        graph,
        list(node_rows),
        list(edge_rows),
        schema_view=schema_view,
        full_sync=full_sync,
        source_sha256="x",
        format=fmt,
        uploaded_by_id=actor.pk,
    )


class TestNodeVerdicts:
    def test_new_node_id_is_create(self, graph, schema_view, actor):
        plan = _plan(
            graph, schema_view, actor, node_rows=[{"node_id": "node-x", "name": "New"}]
        )
        assert plan.node_results[0].verdict == VERDICT_CREATE

    def test_unchanged_existing_node_is_noop(self, graph, schema_view, actor, node_a):
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-a", "name": "Buckthorn", "entity_term": "buckthorn"}
            ],
        )
        assert plan.node_results[0].verdict == VERDICT_NOOP

    def test_changed_existing_node_is_update_with_changed_fields(
        self, graph, schema_view, actor, node_a
    ):
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {
                    "node_id": "node-a",
                    "name": "Buckthorn",
                    "entity_term": "shrub-buckthorn",
                }
            ],
        )
        row = plan.node_results[0]
        assert row.verdict == VERDICT_UPDATE
        assert row.changed_fields["entity_term"] == ("buckthorn", "shrub-buckthorn")

    def test_missing_node_id_is_error(self, graph, schema_view, actor):
        plan = _plan(graph, schema_view, actor, node_rows=[{"name": "No id"}])
        assert plan.node_results[0].verdict == VERDICT_ERROR

    def test_unknown_slot_is_error_but_does_not_abort_other_rows(
        self, graph, schema_view, actor
    ):
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-bad", "not_a_real_slot": "x"},
                {"node_id": "node-good", "name": "Good"},
            ],
        )
        verdicts = {r.id_value: r.verdict for r in plan.node_results}
        assert verdicts["node-bad"] == VERDICT_ERROR
        assert verdicts["node-good"] == VERDICT_CREATE


class TestAnnotatorFieldExcludedFromDiff:
    def test_reimporting_unchanged_export_is_noop_despite_annotator_stamp(
        self, graph, schema_view, actor, node_a
    ):
        # _annotate_with_orcid() stamped data["annotator"] on create, and
        # isn't itself a CAMO schema slot. A re-uploaded row carrying a
        # *different* annotator value (as a real export from someone else
        # would) must still bind cleanly and diff as NOOP on every other
        # field, since apply_import_plan() always re-stamps it anyway.
        node_a.refresh_from_db()
        assert node_a.data.get("annotator")
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {
                    "node_id": "node-a",
                    "name": "Buckthorn",
                    "entity_term": "buckthorn",
                    "annotator": "someone-else",
                }
            ],
        )
        row = plan.node_results[0]
        assert row.verdict == VERDICT_NOOP, row.errors


class TestEdgeReferenceResolution:
    def test_edge_referencing_existing_graph_node_resolves(
        self, graph, schema_view, actor, node_a, node_b
    ):
        plan = _plan(
            graph,
            schema_view,
            actor,
            edge_rows=[
                {
                    "edge_id": "edge-new",
                    "subject_node_id": "node-a",
                    "object_node_id": "node-b",
                }
            ],
        )
        assert plan.edge_results[0].verdict == VERDICT_CREATE

    def test_edge_referencing_node_created_in_same_file_resolves(
        self, graph, schema_view, actor
    ):
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-x", "name": "X"},
                {"node_id": "node-y", "name": "Y"},
            ],
            edge_rows=[
                {
                    "edge_id": "edge-xy",
                    "subject_node_id": "node-x",
                    "object_node_id": "node-y",
                }
            ],
        )
        assert plan.edge_results[0].verdict == VERDICT_CREATE

    def test_edge_referencing_unknown_node_is_error(self, graph, schema_view, actor):
        plan = _plan(
            graph,
            schema_view,
            actor,
            edge_rows=[
                {
                    "edge_id": "edge-bad",
                    "subject_node_id": "ghost",
                    "object_node_id": "also-ghost",
                }
            ],
        )
        assert plan.edge_results[0].verdict == VERDICT_ERROR

    def test_repointing_only_the_endpoints_is_update_not_noop(
        self, graph, schema_view, actor, node_a, node_b
    ):
        node_c = create_node(graph, {"name": "C"}, actor=actor, node_id="node-c")
        create_edge(graph, node_a, node_b, {}, actor=actor, edge_id="edge-1")
        plan = _plan(
            graph,
            schema_view,
            actor,
            edge_rows=[
                {
                    "edge_id": "edge-1",
                    "subject_node_id": "node-a",
                    "object_node_id": node_c.node_id,
                }
            ],
        )
        row = plan.edge_results[0]
        assert row.verdict == VERDICT_UPDATE
        assert row.changed_fields["object_node_id"] == ("node-b", "node-c")

    def test_repointed_edge_apply_actually_updates_the_object(
        self, graph, schema_view, actor, node_a, node_b
    ):
        node_c = create_node(graph, {"name": "C"}, actor=actor, node_id="node-c")
        edge = create_edge(graph, node_a, node_b, {}, actor=actor, edge_id="edge-1")
        plan = _plan(
            graph,
            schema_view,
            actor,
            edge_rows=[
                {
                    "edge_id": "edge-1",
                    "subject_node_id": "node-a",
                    "object_node_id": node_c.node_id,
                }
            ],
        )
        apply_import_plan(plan, actor)
        edge.refresh_from_db()
        assert edge.object_id == node_c.pk


class TestDuplicateIdsWithinFile:
    def test_duplicate_node_id_second_row_is_error_first_still_applies(
        self, graph, schema_view, actor
    ):
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-a", "name": "First"},
                {"node_id": "node-a", "name": "Second"},
            ],
        )
        assert plan.node_results[0].verdict == VERDICT_CREATE
        assert plan.node_results[1].verdict == VERDICT_ERROR

    def test_duplicate_edge_id_second_row_is_error(
        self, graph, schema_view, actor, node_a, node_b
    ):
        plan = _plan(
            graph,
            schema_view,
            actor,
            edge_rows=[
                {
                    "edge_id": "edge-1",
                    "subject_node_id": "node-a",
                    "object_node_id": "node-b",
                },
                {
                    "edge_id": "edge-1",
                    "subject_node_id": "node-b",
                    "object_node_id": "node-a",
                },
            ],
        )
        assert plan.edge_results[0].verdict == VERDICT_CREATE
        assert plan.edge_results[1].verdict == VERDICT_ERROR


class TestNestedFieldsetFlattening:
    def test_nested_evidential_basis_dict_binds(
        self, graph, schema_view, actor, node_a, node_b
    ):
        plan = _plan(
            graph,
            schema_view,
            actor,
            edge_rows=[
                {
                    "edge_id": "edge-1",
                    "subject_node_id": "node-a",
                    "object_node_id": "node-b",
                    "evidential_basis": {
                        "study_design": "observational",
                        "n_observations": "12",
                    },
                }
            ],
        )
        row = plan.edge_results[0]
        assert row.verdict == VERDICT_CREATE, row.errors
        assert row.bound_data["evidential_basis"]["study_design"] == "observational"


class TestFullSync:
    def test_untouched_node_marked_would_delete(
        self, graph, schema_view, actor, node_a, node_b
    ):
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-a", "name": "Buckthorn", "entity_term": "buckthorn"}
            ],
            full_sync=True,
        )
        verdicts = {r.id_value: r.verdict for r in plan.node_results}
        assert verdicts["node-a"] == VERDICT_NOOP
        assert verdicts["node-b"] == VERDICT_WOULD_DELETE

    def test_edge_kept_while_its_node_is_deleted_becomes_error(
        self, graph, schema_view, actor, node_a, node_b
    ):
        create_edge(graph, node_a, node_b, {}, actor=actor, edge_id="edge-1")
        # File only re-declares node-a and the edge — node-b is omitted, so
        # under full sync node-b would be deleted, orphaning this edge.
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-a", "name": "Buckthorn", "entity_term": "buckthorn"}
            ],
            edge_rows=[
                {
                    "edge_id": "edge-1",
                    "subject_node_id": "node-a",
                    "object_node_id": "node-b",
                }
            ],
            full_sync=True,
        )
        edge_row = plan.edge_results[0]
        assert edge_row.verdict == VERDICT_ERROR
        assert any("node-b" in e for e in edge_row.errors)

    def test_error_row_for_existing_node_under_full_sync_is_not_deleted(
        self, graph, schema_view, actor, node_a
    ):
        # A row that fails validation is still *present* in the file — it
        # must not be treated as "absent" and have its existing baseline
        # node deleted out from under the typo.
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[{"node_id": "node-a", "not_a_real_slot": "x"}],
            full_sync=True,
        )
        node_a_rows = [r for r in plan.node_results if r.id_value == "node-a"]
        assert len(node_a_rows) == 1
        assert node_a_rows[0].verdict == VERDICT_ERROR

        apply_import_plan(plan, actor)
        assert Node.objects.filter(graph=graph, node_id="node-a").exists()

    def test_error_row_for_existing_edge_under_full_sync_is_not_deleted(
        self, graph, schema_view, actor, node_a, node_b
    ):
        # Both endpoints are re-declared unchanged (so full sync has no
        # reason to delete either node) — the only failure is the edge
        # row's own bad slot. That row being ERROR must not also produce a
        # second, independent WOULD_DELETE row for the same edge_id.
        create_edge(graph, node_a, node_b, {}, actor=actor, edge_id="edge-1")
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-a", "name": "Buckthorn", "entity_term": "buckthorn"},
                {"node_id": "node-b", "name": "Soil nitrogen", "entity_term": "soil-n"},
            ],
            edge_rows=[
                {
                    "edge_id": "edge-1",
                    "subject_node_id": "node-a",
                    "object_node_id": "node-b",
                    "not_a_real_slot": "x",
                }
            ],
            full_sync=True,
        )
        edge_1_rows = [r for r in plan.edge_results if r.id_value == "edge-1"]
        assert len(edge_1_rows) == 1
        assert edge_1_rows[0].verdict == VERDICT_ERROR

        apply_import_plan(plan, actor)
        assert Edge.objects.filter(graph=graph, edge_id="edge-1").exists()

    def test_edge_cascade_deleted_with_its_node_even_if_edge_row_also_errored(
        self, graph, schema_view, actor, node_a, node_b
    ):
        # node-b is genuinely absent from this file (full sync deletes it);
        # edge-1's own row is independently invalid. There is no "kept"
        # edge here to protect — node-b's deletion legitimately cascades to
        # edge-1 regardless of its unrelated validation error.
        create_edge(graph, node_a, node_b, {}, actor=actor, edge_id="edge-1")
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-a", "name": "Buckthorn", "entity_term": "buckthorn"}
            ],
            edge_rows=[
                {
                    "edge_id": "edge-1",
                    "subject_node_id": "node-a",
                    "object_node_id": "node-b",
                    "not_a_real_slot": "x",
                }
            ],
            full_sync=True,
        )
        apply_import_plan(plan, actor)
        assert not Node.objects.filter(graph=graph, node_id="node-b").exists()
        assert not Edge.objects.filter(graph=graph, edge_id="edge-1").exists()


class TestApplyImportPlan:
    def test_apply_creates_nodes_and_edges_with_specified_ids(
        self, graph, schema_view, actor
    ):
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-a", "name": "A"},
                {"node_id": "node-b", "name": "B"},
            ],
            edge_rows=[
                {
                    "edge_id": "edge-1",
                    "subject_node_id": "node-a",
                    "object_node_id": "node-b",
                }
            ],
        )
        counts = apply_import_plan(plan, actor)
        assert counts["nodes_create"] == 2
        assert counts["edges_create"] == 1
        assert Node.objects.filter(graph=graph, node_id="node-a").exists()
        assert Edge.objects.filter(graph=graph, edge_id="edge-1").exists()

    def test_apply_updates_existing_row_in_place(
        self, graph, schema_view, actor, node_a
    ):
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-a", "name": "Buckthorn", "entity_term": "renamed"}
            ],
        )
        apply_import_plan(plan, actor)
        node_a.refresh_from_db()
        assert node_a.data["entity_term"] == "renamed"
        assert Node.objects.filter(graph=graph).count() == 1

    def test_apply_skips_noop_rows_without_writing(
        self, graph, schema_view, actor, node_a
    ):
        node_a.refresh_from_db()
        original_updated = node_a.data
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-a", "name": "Buckthorn", "entity_term": "buckthorn"}
            ],
        )
        counts = apply_import_plan(plan, actor)
        assert counts["nodes_noop"] == 1
        assert counts["nodes_update"] == 0
        node_a.refresh_from_db()
        assert node_a.data == original_updated

    def test_apply_emits_wrapping_graph_import_audit_event(
        self, graph, schema_view, actor
    ):
        from apps.audit.models import AuditEvent

        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[{"node_id": "node-a", "name": "A"}],
            fmt="xlsx",
        )
        apply_import_plan(plan, actor)
        events = AuditEvent.objects.filter(
            action="graph.import", target_id=str(graph.pk)
        )
        assert events.count() == 1
        assert events.first().diff["format"] == "xlsx"

    def test_full_sync_apply_deletes_untouched_rows(
        self, graph, schema_view, actor, node_a, node_b
    ):
        create_edge(graph, node_a, node_b, {}, actor=actor, edge_id="edge-1")
        plan = _plan(
            graph,
            schema_view,
            actor,
            node_rows=[
                {"node_id": "node-a", "name": "Buckthorn", "entity_term": "buckthorn"}
            ],
            full_sync=True,
        )
        apply_import_plan(plan, actor)
        assert not Node.objects.filter(graph=graph, node_id="node-b").exists()
        assert not Edge.objects.filter(graph=graph, edge_id="edge-1").exists()
        assert Node.objects.filter(graph=graph, node_id="node-a").exists()
