from django.urls import path

from .views import (
    AdjudicateEdgeView,
    AnnotationView,
    EdgeAdvanceView,
    EdgeCreateView,
    EdgeEditView,
    EdgeFormView,
    GraphOntologySnapshotUpgradeView,
    GraphPanelView,
    GraphView,
    HeartbeatView,
    NodeCreateView,
    NodeDeleteView,
    NodeEditView,
    NodeFormView,
    ReturnAssignmentView,
    ReviewDocumentView,
    SchemaDemoView,
    SourceDocumentFormView,
    SourceDocumentSaveView,
    SubmitAnnotationView,
)

urlpatterns = [
    # Schema-driven form demo (Phase 2 acceptance test)
    path("demo/", SchemaDemoView.as_view(), name="schema-demo"),
    # Session heartbeat
    path(
        "sessions/<int:session_pk>/heartbeat/",
        HeartbeatView.as_view(),
        name="heartbeat",
    ),
    # Main annotation surface
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/",
        AnnotationView.as_view(),
        name="annotate",
    ),
    # Graph panel HTMX partial
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/graph/",
        GraphPanelView.as_view(),
        name="graph-panel",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/ontology-snapshot/upgrade/",
        GraphOntologySnapshotUpgradeView.as_view(),
        name="graph-ontology-snapshot-upgrade",
    ),
    # Nodes
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/nodes/new/",
        NodeFormView.as_view(),
        name="node-form",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/nodes/",
        NodeCreateView.as_view(),
        name="node-create",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/nodes/<int:node_pk>/",
        NodeEditView.as_view(),
        name="node-edit",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/nodes/<int:node_pk>/delete/",
        NodeDeleteView.as_view(),
        name="node-delete",
    ),
    # Source document (once per graph)
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/source-document/",
        SourceDocumentFormView.as_view(),
        name="source-document-form",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/source-document/save/",
        SourceDocumentSaveView.as_view(),
        name="source-document-save",
    ),
    # Edges
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/edges/new/",
        EdgeFormView.as_view(),
        name="edge-form",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/edges/",
        EdgeCreateView.as_view(),
        name="edge-create",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/edges/<int:edge_pk>/",
        EdgeEditView.as_view(),
        name="edge-edit",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/edges/<int:edge_pk>/advance/",
        EdgeAdvanceView.as_view(),
        name="edge-advance",
    ),
    # Submit assignment
    path(
        "<int:pk>/documents/<int:doc_pk>/annotate/submit/",
        SubmitAnnotationView.as_view(),
        name="submit-annotation",
    ),
    # Legacy graph-view URL (redirects to annotate)
    path(
        "<int:pk>/documents/<int:doc_pk>/graph/",
        GraphView.as_view(),
        name="graph-view",
    ),
    # Reviewer views (Phase 7)
    path(
        "<int:pk>/documents/<int:doc_pk>/review/",
        ReviewDocumentView.as_view(),
        name="review-document",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/review/assignments/<int:assignment_pk>/return/",
        ReturnAssignmentView.as_view(),
        name="return-assignment",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/review/graphs/<int:graph_pk>/edges/<int:edge_pk>/adjudicate/",
        AdjudicateEdgeView.as_view(),
        name="adjudicate-edge",
    ),
]
