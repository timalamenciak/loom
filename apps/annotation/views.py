"""Phase 5 annotation views — full annotation surface, session timer, node/edge CRUD."""

import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.views import View

from apps.documents.models import TextSpan
from apps.documents.services import render_highlighted_text
from apps.projects.models import Assignment, Document, Project, ProjectMembership
from apps.schemas.models import SchemaVersion
from apps.schemas.schema_engine import get_schema_view

from .models import CausalGraph, Edge, Node, WorkSession
from .services import (
    _unflatten_post,
    adjudicate_edge,
    advance_edge_status,
    close_session,
    create_edge,
    create_node,
    emit_audit,
    heartbeat,
    open_session,
    update_edge,
    update_node,
)


# ── Shared helpers ────────────────────────────────────────────────────────────


def _load_ui_config():
    from pathlib import Path

    import yaml

    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "loom_ui.yaml"
    try:
        with config_path.open() as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _get_active_schema():
    sv = SchemaVersion.get_active()
    if not sv:
        return None, None
    return sv, get_schema_view(sv)


def _require_member(request, project):
    if request.user.is_superuser:
        return
    if not ProjectMembership.objects.filter(project=project, user=request.user).exists():
        raise PermissionDenied


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _graph_nodes_edges(graph):
    nodes = list(graph.nodes.order_by("name"))
    edges = list(graph.edges.select_related("subject", "object").order_by("-created_at"))
    return nodes, edges


def _graph_panel_ctx(project, document, graph):
    nodes, edges = _graph_nodes_edges(graph)
    return {
        "project": project,
        "document": document,
        "graph": graph,
        "nodes": nodes,
        "edges": edges,
    }


# ── Main annotation surface ───────────────────────────────────────────────────


class AnnotationView(LoginRequiredMixin, View):
    template_name = "annotation/annotate.html"

    def get(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)

        schema_version, lsv = _get_active_schema()
        if not lsv:
            messages.error(request, "No active schema. Ask an admin to load one.")
            return redirect("project-detail", pk=pk)

        # Get or create graph for this annotator
        graph, created = CausalGraph.objects.get_or_create(
            document=document,
            annotator=request.user,
            defaults={"schema_version": schema_version},
        )
        if created:
            emit_audit(request.user, "graph.create", "CausalGraph", graph.pk)

        # Session tracking via assignment
        assignment = Assignment.objects.filter(
            document=document, annotator=request.user
        ).first()

        session = None
        if assignment:
            # Link graph to assignment if not already set
            if not assignment.graph_id:
                assignment.graph = graph
                assignment.save(update_fields=["graph"])
            # Advance assignment to in_progress on first open
            if assignment.status == Assignment.STATUS_ASSIGNED:
                assignment.status = Assignment.STATUS_IN_PROGRESS
                assignment.save(update_fields=["status"])
                emit_audit(
                    request.user, "assignment.in_progress", "Assignment", assignment.pk
                )
            session = open_session(assignment, request.user)

        # Canonical text with span highlights
        spans = list(TextSpan.objects.filter(document=document).order_by("start_char"))
        highlighted_text = ""
        if document.canonical_text:
            highlighted_text = mark_safe(
                render_highlighted_text(document.canonical_text, spans)
            )

        # Form specs from active schema
        ui = _load_ui_config()
        node_spec = lsv.form_spec(
            "CausalNode", ontology_routing=ui.get("ontology_routing", {})
        )
        edge_spec = lsv.form_spec(
            "CausalEdge",
            ui_layers=ui.get("layers"),
            ontology_routing=ui.get("ontology_routing", {}),
        )

        nodes, edges = _graph_nodes_edges(graph)

        return render(
            request,
            self.template_name,
            {
                "project": project,
                "document": document,
                "graph": graph,
                "assignment": assignment,
                "session": session,
                "nodes": nodes,
                "edges": edges,
                "node_spec": node_spec,
                "edge_spec": edge_spec,
                "highlighted_text": highlighted_text,
                "spans": spans,
                "graph_nodes": nodes,
            },
        )


# ── Graph panel (HTMX partial refresh) ───────────────────────────────────────


class GraphPanelView(LoginRequiredMixin, View):
    def get(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, document=document, annotator=request.user)
        ctx = _graph_panel_ctx(project, document, graph)
        return render(request, "annotation/partials/graph_panel.html", ctx)


# ── Node views ────────────────────────────────────────────────────────────────


class NodeFormView(LoginRequiredMixin, View):
    """GET → node form partial (HTMX target: #form-panel)."""

    def get(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, document=document, annotator=request.user)

        _, lsv = _get_active_schema()
        ui = _load_ui_config()
        node_spec = lsv.form_spec(
            "CausalNode", ontology_routing=ui.get("ontology_routing", {})
        )

        prefill: dict = {}
        span_pk = request.GET.get("span_pk")
        if span_pk:
            try:
                span = TextSpan.objects.get(pk=int(span_pk), document=document)
                prefill["original_sentence"] = span.text
                prefill["_source_span_pk"] = str(span.pk)
            except (TextSpan.DoesNotExist, ValueError):
                pass

        nodes, _ = _graph_nodes_edges(graph)
        return render(
            request,
            "annotation/partials/node_form.html",
            {
                "project": project,
                "document": document,
                "graph": graph,
                "node_spec": node_spec,
                "current_data": prefill,
                "node": None,
                "graph_nodes": nodes,
            },
        )


class NodeCreateView(LoginRequiredMixin, View):
    def post(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, document=document, annotator=request.user)

        raw = {k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"}
        span_pk = raw.pop("_source_span_pk", None)
        data = _unflatten_post(raw)

        node = create_node(graph, data)
        emit_audit(request.user, "node.create", "Node", node.pk, data)

        if span_pk:
            try:
                span = TextSpan.objects.get(pk=int(span_pk), document=document)
                span.node = node
                span.save(update_fields=["node"])
            except (TextSpan.DoesNotExist, ValueError):
                pass

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph)
            ctx["_oob_clear_form"] = True
            return render(request, "annotation/partials/graph_panel.html", ctx)

        messages.success(request, f'Node "{node.name}" created.')
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


class NodeEditView(LoginRequiredMixin, View):
    def get(self, request, pk, doc_pk, node_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, document=document, annotator=request.user)
        node = get_object_or_404(Node, pk=node_pk, graph=graph)

        _, lsv = _get_active_schema()
        ui = _load_ui_config()
        node_spec = lsv.form_spec(
            "CausalNode", ontology_routing=ui.get("ontology_routing", {})
        )
        nodes, _ = _graph_nodes_edges(graph)
        return render(
            request,
            "annotation/partials/node_form.html",
            {
                "project": project,
                "document": document,
                "graph": graph,
                "node_spec": node_spec,
                "current_data": node.data,
                "node": node,
                "graph_nodes": nodes,
            },
        )

    def post(self, request, pk, doc_pk, node_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, document=document, annotator=request.user)
        node = get_object_or_404(Node, pk=node_pk, graph=graph)

        raw = {k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"}
        data = _unflatten_post(raw)
        update_node(node, data)
        emit_audit(request.user, "node.update", "Node", node.pk, data)

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph)
            ctx["_oob_clear_form"] = True
            return render(request, "annotation/partials/graph_panel.html", ctx)

        messages.success(request, f'Node "{node.name}" updated.')
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


class NodeDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk, doc_pk, node_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, document=document, annotator=request.user)
        node = get_object_or_404(Node, pk=node_pk, graph=graph)

        name = node.name
        emit_audit(request.user, "node.delete", "Node", node.pk)
        node.delete()

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph)
            ctx["_oob_clear_form"] = True
            return render(request, "annotation/partials/graph_panel.html", ctx)

        messages.success(request, f'Node "{name}" deleted.')
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


# ── Edge views ────────────────────────────────────────────────────────────────


def _edge_form_spec(lsv, ui):
    return lsv.form_spec(
        "CausalEdge",
        ui_layers=ui.get("layers"),
        ontology_routing=ui.get("ontology_routing", {}),
    )


class EdgeFormView(LoginRequiredMixin, View):
    """GET → edge form partial (HTMX target: #form-panel)."""

    def get(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, document=document, annotator=request.user)

        _, lsv = _get_active_schema()
        ui = _load_ui_config()
        edge_spec = _edge_form_spec(lsv, ui)
        nodes, _ = _graph_nodes_edges(graph)

        prefill: dict = {}
        span_pk = request.GET.get("span_pk")
        if span_pk:
            try:
                span = TextSpan.objects.get(pk=int(span_pk), document=document)
                prefill["original_sentence"] = span.text
                prefill["_source_span_pk"] = str(span.pk)
            except (TextSpan.DoesNotExist, ValueError):
                pass

        return render(
            request,
            "annotation/partials/edge_form.html",
            {
                "project": project,
                "document": document,
                "graph": graph,
                "edge_spec": edge_spec,
                "current_data": prefill,
                "edge": None,
                "graph_nodes": nodes,
            },
        )


class EdgeCreateView(LoginRequiredMixin, View):
    def post(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, document=document, annotator=request.user)

        raw = {k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"}
        span_pk = raw.pop("_source_span_pk", None)
        subject_id = raw.pop("subject", None)
        object_id = raw.pop("object", None)

        if not subject_id or not object_id:
            if _is_htmx(request):
                return JsonResponse(
                    {"error": "Subject and object nodes are required."}, status=400
                )
            messages.error(request, "Subject and object nodes are required.")
            return redirect("annotate", pk=pk, doc_pk=doc_pk)

        subject = get_object_or_404(Node, graph=graph, node_id=subject_id)
        object_node = get_object_or_404(Node, graph=graph, node_id=object_id)

        data = _unflatten_post(raw)
        edge = create_edge(graph, subject, object_node, data)
        emit_audit(request.user, "edge.create", "Edge", edge.pk, data)

        if span_pk:
            try:
                span = TextSpan.objects.get(pk=int(span_pk), document=document)
                span.edge = edge
                span.save(update_fields=["edge"])
            except (TextSpan.DoesNotExist, ValueError):
                pass

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph)
            ctx["_oob_clear_form"] = True
            return render(request, "annotation/partials/graph_panel.html", ctx)

        messages.success(request, "Edge created.")
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


class EdgeEditView(LoginRequiredMixin, View):
    def get(self, request, pk, doc_pk, edge_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, document=document, annotator=request.user)
        edge = get_object_or_404(Edge, pk=edge_pk, graph=graph)

        _, lsv = _get_active_schema()
        ui = _load_ui_config()
        edge_spec = _edge_form_spec(lsv, ui)
        nodes, _ = _graph_nodes_edges(graph)

        # Merge node IDs into data for node_picker pre-selection
        current_data = dict(edge.data)
        current_data["subject"] = edge.subject.node_id
        current_data["object"] = edge.object.node_id

        return render(
            request,
            "annotation/partials/edge_form.html",
            {
                "project": project,
                "document": document,
                "graph": graph,
                "edge_spec": edge_spec,
                "current_data": current_data,
                "edge": edge,
                "graph_nodes": nodes,
            },
        )

    def post(self, request, pk, doc_pk, edge_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, document=document, annotator=request.user)
        edge = get_object_or_404(Edge, pk=edge_pk, graph=graph)

        raw = {k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"}
        subject_id = raw.pop("subject", None)
        object_id = raw.pop("object", None)

        subject = (
            get_object_or_404(Node, graph=graph, node_id=subject_id) if subject_id else None
        )
        object_node = (
            get_object_or_404(Node, graph=graph, node_id=object_id) if object_id else None
        )

        data = _unflatten_post(raw)
        update_edge(edge, data, subject=subject, object_node=object_node)
        emit_audit(request.user, "edge.update", "Edge", edge.pk, data)

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph)
            ctx["_oob_clear_form"] = True
            return render(request, "annotation/partials/graph_panel.html", ctx)

        messages.success(request, "Edge updated.")
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


class EdgeAdvanceView(LoginRequiredMixin, View):
    def post(self, request, pk, doc_pk, edge_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, document=document, annotator=request.user)
        edge = get_object_or_404(Edge, pk=edge_pk, graph=graph)

        old_status = edge.status
        advance_edge_status(edge, request.user)
        emit_audit(
            request.user,
            "edge.advance",
            "Edge",
            edge.pk,
            {"from": old_status, "to": edge.status},
        )

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph)
            return render(request, "annotation/partials/graph_panel.html", ctx)

        return redirect("annotate", pk=pk, doc_pk=doc_pk)


# ── Session heartbeat ─────────────────────────────────────────────────────────


class HeartbeatView(LoginRequiredMixin, View):
    def post(self, request, session_pk):
        session = get_object_or_404(WorkSession, pk=session_pk, annotator=request.user)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        active_delta = max(0, int(data.get("active_delta", 0)))
        idle_delta = max(0, int(data.get("idle_delta", 0)))
        ended = bool(data.get("ended", False))

        heartbeat(session, active_delta, idle_delta)
        if ended:
            close_session(session)

        return JsonResponse({"ok": True, "active_seconds": session.active_seconds})


# ── Submit assignment ─────────────────────────────────────────────────────────


class SubmitAnnotationView(LoginRequiredMixin, View):
    def post(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_member(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = get_object_or_404(
            Assignment, document=document, annotator=request.user
        )

        # Close all open sessions
        for s in WorkSession.objects.filter(assignment=assignment, ended_at__isnull=True):
            close_session(s)

        submittable = {Assignment.STATUS_ASSIGNED, Assignment.STATUS_IN_PROGRESS}
        if assignment.status in submittable:
            assignment.status = Assignment.STATUS_SUBMITTED
            assignment.save(update_fields=["status"])
            emit_audit(request.user, "assignment.submit", "Assignment", assignment.pk)
            messages.success(request, "Work submitted for review.")
        else:
            messages.info(
                request, f"Assignment is already {assignment.get_status_display()}."
            )

        return redirect("my-queue")


# ── Reviewer views (Phase 7) ─────────────────────────────────────────────────


def _require_reviewer_or_admin(request, project):
    if request.user.is_superuser:
        return
    try:
        m = ProjectMembership.objects.get(project=project, user=request.user)
        if m.role not in (ProjectMembership.ROLE_REVIEWER, ProjectMembership.ROLE_ADMIN):
            raise PermissionDenied
    except ProjectMembership.DoesNotExist:
        raise PermissionDenied


class ReviewDocumentView(LoginRequiredMixin, View):
    """Reviewer/admin view: all annotators' graphs for one document."""

    def get(self, request, pk, doc_pk):
        from django.db.models import Sum

        project = get_object_or_404(Project, pk=pk)
        _require_reviewer_or_admin(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)

        assignments = (
            Assignment.objects.filter(document=document)
            .select_related("annotator", "graph")
            .order_by("assigned_at")
        )

        annotator_data = []
        for assignment in assignments:
            graph = assignment.graph
            nodes, edges = _graph_nodes_edges(graph) if graph else ([], [])
            active = (
                WorkSession.objects.filter(assignment=assignment)
                .aggregate(Sum("active_seconds"))["active_seconds__sum"]
                or 0
            )
            annotator_data.append(
                {
                    "assignment": assignment,
                    "graph": graph,
                    "nodes": nodes,
                    "edges": edges,
                    "active_seconds": active,
                    "active_minutes": round(active / 60, 1),
                }
            )

        is_admin = request.user.is_superuser or ProjectMembership.objects.filter(
            project=project, user=request.user, role=ProjectMembership.ROLE_ADMIN
        ).exists()

        return render(
            request,
            "annotation/review_document.html",
            {
                "project": project,
                "document": document,
                "annotator_data": annotator_data,
                "is_admin": is_admin,
            },
        )


class AdjudicateEdgeView(LoginRequiredMixin, View):
    """POST: reviewer advances a specific graph's edge (complete→reviewed or reviewed→gold)."""

    def post(self, request, pk, doc_pk, graph_pk, edge_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_reviewer_or_admin(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, pk=graph_pk, document=document)
        edge = get_object_or_404(Edge, pk=edge_pk, graph=graph)

        old_status = edge.status
        adjudicate_edge(edge, request.user)
        emit_audit(
            request.user,
            "edge.adjudicate",
            "Edge",
            edge.pk,
            {"from": old_status, "to": edge.status},
        )

        return redirect("review-document", pk=pk, doc_pk=doc_pk)


# ── Schema demo (Phase 2 acceptance helper) ───────────────────────────────────


class SchemaDemoView(LoginRequiredMixin, View):
    def get(self, request):
        schema_version, lsv = _get_active_schema()
        if not lsv:
            return render(request, "annotation/schema_demo.html", {"schema_version": None})

        ui = _load_ui_config()
        edge_spec = lsv.form_spec(
            "CausalEdge",
            ui_layers=ui.get("layers"),
            ontology_routing=ui.get("ontology_routing", {}),
        )
        node_spec = lsv.form_spec("CausalNode", ontology_routing=ui.get("ontology_routing", {}))

        return render(
            request,
            "annotation/schema_demo.html",
            {
                "schema_version": schema_version,
                "edge_spec": edge_spec,
                "node_spec": node_spec,
                "all_classes": lsv.class_names(),
            },
        )


# ── Legacy stub (redirects to Phase 5 surface) ───────────────────────────────


class GraphView(LoginRequiredMixin, View):
    def get(self, request, pk, doc_pk):
        return redirect("annotate", pk=pk, doc_pk=doc_pk)

    def post(self, request, pk, doc_pk):
        return redirect("annotate", pk=pk, doc_pk=doc_pk)
