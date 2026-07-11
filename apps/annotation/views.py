"""Phase 5 annotation views — full annotation surface, session timer, node/edge CRUD."""

import hashlib
import json
import logging
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.utils.text import slugify
from django.views import View

from apps.documents.models import TextSpan
from apps.documents.services import ensure_canonical_text, render_highlighted_text
from apps.export.serializer import serialize_graph
from apps.export.validators import validate_graph_data
from apps.ontology.adhoc import resolve_wd_curies_in_data
from apps.ontology.validation import add_ontology_errors
from apps.projects.models import Assignment, Document, Project, ProjectMembership
from apps.schemas.models import SchemaVersion
from apps.schemas.schema_engine import get_schema_view

from .models import CausalGraph, Edge, Node, WorkSession
from .policies import (
    assignment_is_editable,
    require_annotation_assignment,
    require_editable_assignment,
)
from .services import (
    _preprocess_source_document,
    adjudicate_edge,
    advance_edge_status,
    close_session,
    create_edge,
    create_graph,
    create_node,
    delete_node,
    emit_audit,
    heartbeat,
    open_session,
    set_edge_source_spans,
    set_node_source_spans,
    update_edge,
    update_graph_source_document,
    update_node,
    upgrade_graph_ontology_snapshot,
)

logger = logging.getLogger(__name__)

_NODE_MANAGED_SLOTS = frozenset({"node_id", "source_spans", "id"})
_EDGE_MANAGED_SLOTS = frozenset({"edge_id", "subject", "object", "source_spans", "id"})


def _auto_node_id(data: dict) -> str:
    """Generate a stable CURIE-style node id from entity_term or name."""
    entity_term = (data.get("entity_term") or "").strip()
    if entity_term and ":" in entity_term:
        return entity_term
    name = (data.get("name") or "").strip()
    if name:
        slug = slugify(name)[:40]
        suffix = hashlib.md5(name.encode()).hexdigest()[:6]
        return f"causal_mosaic:{slug}_{suffix}"
    return f"causal_mosaic:node_{uuid.uuid4().hex[:8]}"


def _auto_edge_id() -> str:
    return f"causal_mosaic:edge_{uuid.uuid4().hex[:8]}"


# ── Shared helpers ────────────────────────────────────────────────────────────


def _load_ui_config():
    from pathlib import Path

    import yaml
    from django.conf import settings

    config_path = Path(settings.BASE_DIR) / "config" / "loom_ui.yaml"
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


def get_schema_version(project):
    """The schema a new graph in *project* should be pinned to.

    A project's own `active_schema` override wins; otherwise fall back to
    whichever SchemaVersion is system-active.
    """
    return project.active_schema or SchemaVersion.get_active()


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _graph_nodes_edges(graph):
    nodes = list(graph.nodes.order_by("name"))
    edges = list(
        graph.edges.select_related("subject", "object").order_by("-created_at")
    )
    return nodes, edges


def _graph_panel_ctx(project, document, graph, assignment):
    nodes, edges = _graph_nodes_edges(graph)
    spans = list(
        TextSpan.objects.filter(document=document, created_by=assignment.annotator)
        .select_related("node", "edge")
        .order_by("start_char")
    )
    return {
        "project": project,
        "document": document,
        "graph": graph,
        "nodes": nodes,
        "edges": edges,
        "assignment": assignment,
        "can_edit": assignment_is_editable(assignment),
        "spans": spans,
        "can_edit_spans": assignment_is_editable(assignment),
    }


def _post_payload(request, *managed_names):
    """Return a mutable QueryDict and selected Loom-managed values.

    Also strips `<slot>_wd_label` / `<slot>_wd_def` — the Wikidata hint hidden
    inputs form_field.html renders next to any ontology_autocomplete field with
    `wikidata_live` set (see static/js/ontology-autocomplete.js's _selectTerm).
    They are never schema slots, so the generic binder (apps/schemas/
    input_binding.py) rejects them outright as undefined fields; that made
    saving any node/edge with a wikidata_live field (e.g. entity_term,
    ecosystem_context) fail unconditionally. resolve_wd_curies_in_data reads
    them straight off `request.POST` separately, so stripping them here from
    the binder's payload doesn't lose anything.
    """
    payload = request.POST.copy()
    if "csrfmiddlewaretoken" in payload:
        payload.pop("csrfmiddlewaretoken")
    for name in [k for k in payload if k.endswith(("_wd_label", "_wd_def"))]:
        payload.pop(name)
    managed = {}
    for name in managed_names:
        managed[name] = payload.get(name)
        if name in payload:
            payload.pop(name)
    return payload, managed


def _parse_span_ids(values) -> list[int]:
    parsed: list[int] = []
    for value in values:
        for part in str(value or "").split(","):
            try:
                span_id = int(part.strip())
            except ValueError:
                continue
            if span_id > 0 and span_id not in parsed:
                parsed.append(span_id)
    return parsed


def _requested_span_ids(request) -> list[int]:
    values = request.POST.getlist("source_spans")
    values.extend(request.POST.getlist("_source_span_pks"))
    legacy = request.POST.get("_source_span_pk")
    if legacy:
        values.append(legacy)
    return _parse_span_ids(values)


def _query_span_ids(request) -> list[int]:
    values = request.GET.getlist("span_pks")
    legacy = request.GET.get("span_pk")
    if legacy:
        values.append(legacy)
    return _parse_span_ids(values)


def _grounding_options(
    document,
    user,
    *,
    target_kind: str,
    target=None,
    selected_ids=None,
):
    has_explicit_selection = selected_ids is not None
    selected = set(selected_ids or [])
    target_id = getattr(target, "pk", None)
    options = []
    spans = (
        TextSpan.objects.filter(document=document, created_by=user)
        .select_related("node", "edge")
        .order_by("start_char")
    )
    for span in spans:
        linked_id = span.node_id if target_kind == "node" else span.edge_id
        unavailable = linked_id is not None and linked_id != target_id
        options.append(
            {
                "span": span,
                "selected": not unavailable
                and (
                    span.pk in selected
                    if has_explicit_selection
                    else linked_id == target_id
                ),
                "unavailable": unavailable,
            }
        )
    return options


def _selected_spans(document, user, span_ids, *, target_kind, target=None):
    target_id = getattr(target, "pk", None)
    spans = list(
        TextSpan.objects.filter(
            pk__in=span_ids,
            document=document,
            created_by=user,
        ).order_by("start_char")
    )
    if target_kind == "node":
        return [span for span in spans if span.node_id in {None, target_id}]
    return [span for span in spans if span.edge_id in {None, target_id}]


def _excerpt_text(spans) -> str:
    return "\n\n[...]\n\n".join(
        span.text.strip() for span in spans if span.text.strip()
    )


def _form_error_response(request, template_name, context):
    response = render(request, template_name, context, status=422)
    response["HX-Retarget"] = "#form-panel"
    return response


def _node_form_spec(schema_view, project=None):
    ui = _load_ui_config()
    hidden = list(ui.get("globally_hidden_slots", []))
    if project:
        hidden = hidden + [s for s in (project.hidden_slots or []) if s not in hidden]
    return schema_view.form_spec(
        "CausalNode",
        ontology_routing=ui.get("ontology_routing", {}),
        widget_overrides=ui.get("widget_overrides", {}),
        globally_hidden_slots=hidden,
        slot_help_texts=ui.get("slot_help_text", {}),
    )


def _user_graph_queryset(document, user):
    return CausalGraph.objects.filter(document=document, annotator=user).order_by(
        "-updated_at", "-created_at", "-pk"
    )


def _get_or_create_user_graph(
    document, user, schema_version, ontology_snapshot=None, assignment=None
):
    """Return a deterministic graph for this annotator/document pair.

    Older data may contain more than one graph for the same annotator and
    document because the model does not enforce uniqueness. Avoid
    get_or_create(), which raises MultipleObjectsReturned in that case.
    """
    if assignment and assignment.graph_id:
        graph = assignment.graph
        if graph.document_id == document.pk and graph.annotator_id == user.pk:
            return graph, False

    graph = _user_graph_queryset(document, user).first()
    if graph:
        return graph, False

    return (
        create_graph(
            document,
            user,
            schema_version,
            ontology_snapshot=ontology_snapshot,
        ),
        True,
    )


def _get_user_graph_or_404(document, user, assignment=None):
    if assignment and assignment.graph_id:
        graph = assignment.graph
        if graph.document_id == document.pk and graph.annotator_id == user.pk:
            return graph
    graph = _user_graph_queryset(document, user).first()
    if graph is None:
        raise Http404("No annotation graph found.")
    return graph


# ── Main annotation surface ───────────────────────────────────────────────────


class AnnotationView(LoginRequiredMixin, View):
    template_name = "annotation/annotate.html"

    def get(self, request, pk, doc_pk):
        try:
            return self._get(request, pk, doc_pk)
        except (PermissionDenied, Http404):
            raise
        except Exception:
            logger.exception(
                "Annotation workspace failed for project=%s document=%s user=%s",
                pk,
                doc_pk,
                getattr(request.user, "pk", None),
            )
            raise

    def _get(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_annotation_assignment(document, request.user)
        can_edit = assignment_is_editable(assignment)
        ensure_canonical_text(document)

        existing_graph = _user_graph_queryset(document, request.user).first()
        new_graph_schema = get_schema_version(project)
        if not new_graph_schema and not existing_graph:
            messages.error(
                request,
                "This project has no LinkML schema. Ask the owner to configure it.",
            )
            return redirect("project-detail", pk=pk)

        if can_edit:
            graph, _created = _get_or_create_user_graph(
                document,
                request.user,
                new_graph_schema,
                ontology_snapshot=project.ontology_snapshot,
                assignment=assignment,
            )
        else:
            graph = assignment.graph or existing_graph
            if graph is None:
                raise Http404("No submitted annotation graph found.")
        schema_version = graph.schema_version
        lsv = get_schema_view(schema_version, project=project)
        session = None
        if can_edit:
            # Link this assignment to the graph the workspace will use.
            if assignment.graph_id != graph.pk:
                assignment.graph = graph
                assignment.save(update_fields=["graph"])
            # Advance assignment to in_progress on first open
            if assignment.status in {
                Assignment.STATUS_ASSIGNED,
                Assignment.STATUS_RETURNED,
            }:
                old_status = assignment.status
                assignment.status = Assignment.STATUS_IN_PROGRESS
                assignment.save(update_fields=["status"])
                emit_audit(
                    request.user,
                    "assignment.in_progress",
                    "Assignment",
                    assignment.pk,
                    {"from": old_status, "to": assignment.status},
                )
            session = open_session(assignment, request.user)

        # Canonical text with span highlights
        spans = list(
            TextSpan.objects.filter(document=document, created_by=request.user)
            .select_related("node", "edge")
            .order_by("start_char")
        )
        highlighted_text = ""
        if document.canonical_text:
            text_spans = [s for s in spans if s.text_source == "canonical_text"]
            highlighted_text = mark_safe(
                render_highlighted_text(document.canonical_text, text_spans)
            )

        # Marker Markdown → rendered HTML (spans from this view use canonical_markdown offsets)
        markdown_html = ""
        if document.canonical_markdown:
            try:
                import markdown as _md

                markdown_html = mark_safe(
                    _md.markdown(
                        document.canonical_markdown,
                        extensions=["tables", "fenced_code"],
                    )
                )
            except Exception:
                pass

        # Form specs from the graph-pinned schema
        ui = _load_ui_config()
        node_spec = _node_form_spec(lsv, project=project)
        edge_spec = _edge_form_spec(lsv, ui, project=project)

        nodes, edges = _graph_nodes_edges(graph)
        initial_form = request.GET.get("form", "")
        if initial_form not in {"node", "edge"}:
            initial_form = ""
        excerpt_options = []
        if initial_form:
            excerpt_options = _grounding_options(
                document,
                request.user,
                target_kind=initial_form,
                selected_ids=_query_span_ids(request),
            )

        return render(
            request,
            self.template_name,
            {
                "project": project,
                "document": document,
                "graph": graph,
                "assignment": assignment,
                "can_edit": can_edit,
                "session": session,
                "nodes": nodes,
                "edges": edges,
                "node_spec": node_spec,
                "edge_spec": edge_spec,
                "highlighted_text": highlighted_text,
                "markdown_html": markdown_html,
                "spans": spans,
                "graph_nodes": nodes,
                "initial_form": initial_form,
                "empty_form_data": {},
                "excerpt_options": excerpt_options,
                "can_edit_spans": can_edit,
                "ontology_snapshot_update_available": bool(
                    can_edit
                    and project.ontology_snapshot_id
                    and graph.ontology_snapshot_id != project.ontology_snapshot_id
                ),
            },
        )


class GraphOntologySnapshotUpgradeView(LoginRequiredMixin, View):
    """POST: explicitly repin an editable graph to its project snapshot."""

    def post(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)
        if project.ontology_snapshot is None:
            messages.error(request, "This project's ontology cache is not ready yet.")
        else:
            upgrade_graph_ontology_snapshot(
                graph, project.ontology_snapshot, request.user
            )
            messages.success(request, "Graph ontology snapshot updated.")
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


# ── Graph panel (HTMX partial refresh) ───────────────────────────────────────


class GraphPanelView(LoginRequiredMixin, View):
    def get(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_annotation_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)
        ctx = _graph_panel_ctx(project, document, graph, assignment)
        return render(request, "annotation/partials/graph_panel.html", ctx)


# ── Node views ────────────────────────────────────────────────────────────────


class NodeFormView(LoginRequiredMixin, View):
    """GET → node form partial (HTMX target: #form-panel)."""

    def get(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)

        lsv = get_schema_view(graph.schema_version, project=project)
        if not lsv:
            from django.http import HttpResponse

            return HttpResponse(
                '<p class="message message-error" style="padding:1rem">'
                "No active schema — ask an administrator to load one.</p>",
                content_type="text/html; charset=utf-8",
            )
        node_spec = _node_form_spec(lsv, project=project)

        prefill: dict = {}
        selected_ids = _query_span_ids(request)

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
                "assignment": assignment,
                "can_edit": True,
                "excerpt_options": _grounding_options(
                    document,
                    request.user,
                    target_kind="node",
                    selected_ids=selected_ids,
                ),
            },
        )


class NodeCreateView(LoginRequiredMixin, View):
    def post(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)

        span_ids = _requested_span_ids(request)
        payload, _managed = _post_payload(
            request, "source_spans", "_source_span_pk", "_source_span_pks"
        )
        lsv = get_schema_view(graph.schema_version, project=project)
        bound = lsv.bind_form_data(
            "CausalNode", payload, excluded_slots=_NODE_MANAGED_SLOTS
        )
        if bound.is_valid:
            add_ontology_errors(
                bound,
                _node_form_spec(lsv, project=project),
                graph.ontology_snapshot or project.ontology_snapshot,
            )
        if not bound.is_valid:
            current_data = dict(bound.data)
            nodes, _ = _graph_nodes_edges(graph)
            return _form_error_response(
                request,
                "annotation/partials/node_form.html",
                {
                    "project": project,
                    "document": document,
                    "graph": graph,
                    "node_spec": _node_form_spec(lsv, project=project),
                    "current_data": current_data,
                    "form_errors": bound.errors,
                    "node": None,
                    "graph_nodes": nodes,
                    "assignment": assignment,
                    "can_edit": True,
                    "excerpt_options": _grounding_options(
                        document,
                        request.user,
                        target_kind="node",
                        selected_ids=span_ids,
                    ),
                },
            )

        resolve_wd_curies_in_data(project, bound.data, request.POST)
        bound.data["id"] = _auto_node_id(bound.data)
        node = create_node(graph, bound.data, actor=request.user)
        selected_spans = _selected_spans(
            document,
            request.user,
            span_ids,
            target_kind="node",
            target=node,
        )
        set_node_source_spans(node, selected_spans, request.user)

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph, assignment)
            ctx["oob_clear_form"] = True
            ctx["oob_refresh_excerpts"] = True
            return render(request, "annotation/partials/graph_panel.html", ctx)

        messages.success(request, f'Node "{node.name}" created.')
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


class NodeEditView(LoginRequiredMixin, View):
    def get(self, request, pk, doc_pk, node_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)
        node = get_object_or_404(Node, pk=node_pk, graph=graph)

        lsv = get_schema_view(graph.schema_version, project=project)
        if not lsv:
            from django.http import HttpResponse

            return HttpResponse(
                '<p class="message message-error" style="padding:1rem">'
                "No active schema — ask an administrator to load one.</p>",
                content_type="text/html; charset=utf-8",
            )
        node_spec = _node_form_spec(lsv, project=project)
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
                "assignment": assignment,
                "can_edit": True,
                "excerpt_options": _grounding_options(
                    document,
                    request.user,
                    target_kind="node",
                    target=node,
                ),
            },
        )

    def post(self, request, pk, doc_pk, node_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)
        node = get_object_or_404(Node, pk=node_pk, graph=graph)

        span_ids = _requested_span_ids(request)
        payload, _managed = _post_payload(
            request, "source_spans", "_source_span_pk", "_source_span_pks"
        )
        lsv = get_schema_view(graph.schema_version, project=project)
        bound = lsv.bind_form_data(
            "CausalNode", payload, excluded_slots=_NODE_MANAGED_SLOTS
        )
        if bound.is_valid:
            add_ontology_errors(
                bound,
                _node_form_spec(lsv, project=project),
                graph.ontology_snapshot or project.ontology_snapshot,
            )
        if not bound.is_valid:
            nodes, _ = _graph_nodes_edges(graph)
            return _form_error_response(
                request,
                "annotation/partials/node_form.html",
                {
                    "project": project,
                    "document": document,
                    "graph": graph,
                    "node_spec": _node_form_spec(lsv, project=project),
                    "current_data": bound.data,
                    "form_errors": bound.errors,
                    "node": node,
                    "graph_nodes": nodes,
                    "assignment": assignment,
                    "can_edit": True,
                    "excerpt_options": _grounding_options(
                        document,
                        request.user,
                        target_kind="node",
                        target=node,
                        selected_ids=span_ids,
                    ),
                },
            )
        resolve_wd_curies_in_data(project, bound.data, request.POST)
        bound.data["id"] = node.data.get("id") or _auto_node_id(bound.data)
        update_node(node, bound.data, actor=request.user)
        selected_spans = _selected_spans(
            document,
            request.user,
            span_ids,
            target_kind="node",
            target=node,
        )
        set_node_source_spans(node, selected_spans, request.user)

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph, assignment)
            ctx["oob_clear_form"] = True
            ctx["oob_refresh_excerpts"] = True
            return render(request, "annotation/partials/graph_panel.html", ctx)

        messages.success(request, f'Node "{node.name}" updated.')
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


class NodeDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk, doc_pk, node_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)
        node = get_object_or_404(Node, pk=node_pk, graph=graph)

        name = node.name
        delete_node(node, request.user)

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph, assignment)
            ctx["oob_clear_form"] = True
            ctx["oob_refresh_excerpts"] = True
            return render(request, "annotation/partials/graph_panel.html", ctx)

        messages.success(request, f'Node "{name}" deleted.')
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


# ── Edge views ────────────────────────────────────────────────────────────────


def _edge_form_spec(lsv, ui, project=None):
    hidden = list(ui.get("globally_hidden_slots", []))
    if project:
        hidden = hidden + [s for s in (project.hidden_slots or []) if s not in hidden]
    return lsv.form_spec(
        "CausalEdge",
        ui_layers=ui.get("layers"),
        ontology_routing=ui.get("ontology_routing", {}),
        widget_overrides=ui.get("widget_overrides", {}),
        globally_hidden_slots=hidden,
        slot_help_texts=ui.get("slot_help_text", {}),
    )


def _source_doc_initial(document, graph) -> dict:
    """Merge document bib fields (base) with any already-saved annotator data."""
    bib: dict = {}
    if document.doi:
        bib["doi"] = document.doi
    if document.title:
        bib["title"] = document.title
    if document.authors:
        bib["authors"] = list(document.authors)
    if document.year:
        bib["year"] = document.year
    if document.journal:
        bib["journal"] = document.journal
    return {**bib, **(graph.source_document or {})}


class SourceDocumentFormView(LoginRequiredMixin, View):
    """GET → source-document form partial (HTMX target: #form-panel)."""

    def get(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)

        lsv = get_schema_view(graph.schema_version, project=project)
        if not lsv:
            from django.http import HttpResponse

            return HttpResponse(
                '<p class="message message-error" style="padding:1rem">'
                "No active schema — ask an administrator to load one.</p>",
                content_type="text/html; charset=utf-8",
            )
        ui = _load_ui_config()
        sd_spec = lsv.form_spec(
            "SourceDocument",
            ui_layers=ui.get("source_document_layers"),
            ontology_routing=ui.get("ontology_routing", {}),
            widget_overrides=ui.get("widget_overrides", {}),
            globally_hidden_slots=ui.get("globally_hidden_slots", []),
            geonames_autofill=ui.get("geonames_autofill", {}),
            coordinate_list_fields=ui.get("coordinate_list_fields", {}),
        )
        initial = _source_doc_initial(document, graph)
        rules = document.project.source_document_rollup or []
        if rules:
            from apps.annotation.rollup import roll_up_source_document

            nodes_data = list(graph.nodes.values_list("data", flat=True))
            edges_data = list(graph.edges.values_list("data", flat=True))
            rolled = roll_up_source_document(nodes_data, edges_data, rules)
            saved = graph.source_document or {}
            for slot, value in rolled.items():
                if slot not in saved:
                    initial.setdefault(slot, value)
        return render(
            request,
            "annotation/partials/source_document_form.html",
            {
                "project": project,
                "document": document,
                "graph": graph,
                "sd_spec": sd_spec,
                "current_data": initial,
                "assignment": assignment,
                "geonames_configured": bool(settings.GEONAMES_USERNAME),
            },
        )


class SourceDocumentSaveView(LoginRequiredMixin, View):
    """POST → save source-document to the graph; refresh graph panel."""

    def post(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)

        lsv = get_schema_view(graph.schema_version, project=project)
        payload, _ = _post_payload(request)
        bound = lsv.bind_form_data("SourceDocument", payload)
        ui = _load_ui_config()
        sd_spec = lsv.form_spec(
            "SourceDocument",
            ui_layers=ui.get("source_document_layers"),
            ontology_routing=ui.get("ontology_routing", {}),
            widget_overrides=ui.get("widget_overrides", {}),
            globally_hidden_slots=ui.get("globally_hidden_slots", []),
            geonames_autofill=ui.get("geonames_autofill", {}),
            coordinate_list_fields=ui.get("coordinate_list_fields", {}),
        )
        if bound.is_valid:
            add_ontology_errors(
                bound,
                sd_spec,
                graph.ontology_snapshot or project.ontology_snapshot,
            )

        if not bound.is_valid:
            return _form_error_response(
                request,
                "annotation/partials/source_document_form.html",
                {
                    "project": project,
                    "document": document,
                    "graph": graph,
                    "sd_spec": sd_spec,
                    "current_data": dict(bound.data),
                    "form_errors": bound.errors,
                    "assignment": assignment,
                    "geonames_configured": bool(settings.GEONAMES_USERNAME),
                },
            )

        data = _preprocess_source_document(bound.data)
        update_graph_source_document(graph, data, actor=request.user)

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph, assignment)
            ctx["oob_clear_form"] = True
            return render(request, "annotation/partials/graph_panel.html", ctx)

        messages.success(request, "Source document saved.")
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


class EdgeFormView(LoginRequiredMixin, View):
    """GET → edge form partial (HTMX target: #form-panel)."""

    def get(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)

        lsv = get_schema_view(graph.schema_version, project=project)
        if not lsv:
            from django.http import HttpResponse

            return HttpResponse(
                '<p class="message message-error" style="padding:1rem">'
                "No active schema — ask an administrator to load one.</p>",
                content_type="text/html; charset=utf-8",
            )
        ui = _load_ui_config()
        edge_spec = _edge_form_spec(lsv, ui, project=project)
        nodes, _ = _graph_nodes_edges(graph)

        selected_ids = _query_span_ids(request)
        selected_spans = _selected_spans(
            document,
            request.user,
            selected_ids,
            target_kind="edge",
        )
        prefill: dict = {}
        if selected_spans:
            prefill["original_sentence"] = _excerpt_text(selected_spans)

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
                "assignment": assignment,
                "can_edit": True,
                "excerpt_options": _grounding_options(
                    document,
                    request.user,
                    target_kind="edge",
                    selected_ids=selected_ids,
                ),
            },
        )


class EdgeCreateView(LoginRequiredMixin, View):
    def post(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)

        span_ids = _requested_span_ids(request)
        payload, managed = _post_payload(
            request,
            "_source_span_pk",
            "_source_span_pks",
            "source_spans",
            "subject",
            "object",
        )
        subject_id = managed["subject"]
        object_id = managed["object"]

        if not subject_id or not object_id:
            if _is_htmx(request):
                return JsonResponse(
                    {"error": "Subject and object nodes are required."}, status=400
                )
            messages.error(request, "Subject and object nodes are required.")
            return redirect("annotate", pk=pk, doc_pk=doc_pk)

        subject = get_object_or_404(Node, graph=graph, node_id=subject_id)
        object_node = get_object_or_404(Node, graph=graph, node_id=object_id)

        lsv = get_schema_view(graph.schema_version, project=project)
        bound = lsv.bind_form_data(
            "CausalEdge", payload, excluded_slots=_EDGE_MANAGED_SLOTS
        )
        if bound.is_valid:
            add_ontology_errors(
                bound,
                _edge_form_spec(lsv, _load_ui_config(), project=project),
                graph.ontology_snapshot or project.ontology_snapshot,
            )
        if not bound.is_valid:
            current_data = dict(bound.data)
            current_data.update({"subject": subject_id, "object": object_id})
            nodes, _ = _graph_nodes_edges(graph)
            return _form_error_response(
                request,
                "annotation/partials/edge_form.html",
                {
                    "project": project,
                    "document": document,
                    "graph": graph,
                    "edge_spec": _edge_form_spec(
                        lsv, _load_ui_config(), project=project
                    ),
                    "current_data": current_data,
                    "form_errors": bound.errors,
                    "edge": None,
                    "graph_nodes": nodes,
                    "assignment": assignment,
                    "can_edit": True,
                    "excerpt_options": _grounding_options(
                        document,
                        request.user,
                        target_kind="edge",
                        selected_ids=span_ids,
                    ),
                },
            )
        bound.data["id"] = _auto_edge_id()
        edge = create_edge(graph, subject, object_node, bound.data, actor=request.user)
        selected_spans = _selected_spans(
            document,
            request.user,
            span_ids,
            target_kind="edge",
            target=edge,
        )
        set_edge_source_spans(edge, selected_spans, request.user)

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph, assignment)
            ctx["oob_clear_form"] = True
            ctx["oob_refresh_excerpts"] = True
            return render(request, "annotation/partials/graph_panel.html", ctx)

        messages.success(request, "Edge created.")
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


class EdgeEditView(LoginRequiredMixin, View):
    def get(self, request, pk, doc_pk, edge_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)
        edge = get_object_or_404(Edge, pk=edge_pk, graph=graph)

        lsv = get_schema_view(graph.schema_version, project=project)
        if not lsv:
            from django.http import HttpResponse

            return HttpResponse(
                '<p class="message message-error" style="padding:1rem">'
                "No active schema — ask an administrator to load one.</p>",
                content_type="text/html; charset=utf-8",
            )
        ui = _load_ui_config()
        edge_spec = _edge_form_spec(lsv, ui, project=project)
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
                "assignment": assignment,
                "can_edit": True,
                "excerpt_options": _grounding_options(
                    document,
                    request.user,
                    target_kind="edge",
                    target=edge,
                ),
            },
        )

    def post(self, request, pk, doc_pk, edge_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)
        edge = get_object_or_404(Edge, pk=edge_pk, graph=graph)

        span_ids = _requested_span_ids(request)
        payload, managed = _post_payload(
            request,
            "_source_span_pk",
            "_source_span_pks",
            "source_spans",
            "subject",
            "object",
        )
        subject_id = managed["subject"]
        object_id = managed["object"]

        subject = (
            get_object_or_404(Node, graph=graph, node_id=subject_id)
            if subject_id
            else None
        )
        object_node = (
            get_object_or_404(Node, graph=graph, node_id=object_id)
            if object_id
            else None
        )

        lsv = get_schema_view(graph.schema_version, project=project)
        bound = lsv.bind_form_data(
            "CausalEdge", payload, excluded_slots=_EDGE_MANAGED_SLOTS
        )
        if bound.is_valid:
            add_ontology_errors(
                bound,
                _edge_form_spec(lsv, _load_ui_config(), project=project),
                graph.ontology_snapshot or project.ontology_snapshot,
            )
        if not bound.is_valid:
            current_data = dict(bound.data)
            current_data.update(
                {
                    "subject": subject_id or edge.subject.node_id,
                    "object": object_id or edge.object.node_id,
                }
            )
            nodes, _ = _graph_nodes_edges(graph)
            return _form_error_response(
                request,
                "annotation/partials/edge_form.html",
                {
                    "project": project,
                    "document": document,
                    "graph": graph,
                    "edge_spec": _edge_form_spec(
                        lsv, _load_ui_config(), project=project
                    ),
                    "current_data": current_data,
                    "form_errors": bound.errors,
                    "edge": edge,
                    "graph_nodes": nodes,
                    "assignment": assignment,
                    "can_edit": True,
                    "excerpt_options": _grounding_options(
                        document,
                        request.user,
                        target_kind="edge",
                        target=edge,
                        selected_ids=span_ids,
                    ),
                },
            )
        bound.data["id"] = edge.data.get("id") or _auto_edge_id()
        update_edge(
            edge,
            bound.data,
            subject=subject,
            object_node=object_node,
            actor=request.user,
        )
        selected_spans = _selected_spans(
            document,
            request.user,
            span_ids,
            target_kind="edge",
            target=edge,
        )
        set_edge_source_spans(edge, selected_spans, request.user)

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph, assignment)
            ctx["oob_clear_form"] = True
            ctx["oob_refresh_excerpts"] = True
            return render(request, "annotation/partials/graph_panel.html", ctx)

        messages.success(request, "Edge updated.")
        return redirect("annotate", pk=pk, doc_pk=doc_pk)


class EdgeAdvanceView(LoginRequiredMixin, View):
    def post(self, request, pk, doc_pk, edge_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)
        edge = get_object_or_404(Edge, pk=edge_pk, graph=graph)

        advance_edge_status(edge, request.user)

        if _is_htmx(request):
            ctx = _graph_panel_ctx(project, document, graph, assignment)
            return render(request, "annotation/partials/graph_panel.html", ctx)

        return redirect("annotate", pk=pk, doc_pk=doc_pk)


# ── Session heartbeat ─────────────────────────────────────────────────────────


class HeartbeatView(LoginRequiredMixin, View):
    def post(self, request, session_pk):
        session = get_object_or_404(
            WorkSession.objects.select_related("assignment"),
            pk=session_pk,
            annotator=request.user,
        )

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if not isinstance(data, dict):
            return JsonResponse({"error": "JSON body must be an object"}, status=400)
        if session.ended_at is not None:
            return JsonResponse({"error": "Session has already ended"}, status=409)
        if not assignment_is_editable(session.assignment):
            return JsonResponse({"error": "Assignment is read-only"}, status=409)

        try:
            active_delta = _nonnegative_int(data.get("active_delta", 0))
            idle_delta = _nonnegative_int(data.get("idle_delta", 0))
        except (TypeError, ValueError):
            return JsonResponse(
                {"error": "Time deltas must be non-negative integers"}, status=400
            )
        ended = data.get("ended", False)
        if not isinstance(ended, bool):
            return JsonResponse({"error": "ended must be a boolean"}, status=400)

        heartbeat(session, active_delta, idle_delta)
        if ended:
            close_session(session)

        return JsonResponse({"ok": True, "active_seconds": session.active_seconds})


def _nonnegative_int(value) -> int:
    if isinstance(value, bool):
        raise TypeError
    parsed = int(value)
    if parsed < 0:
        raise ValueError
    return parsed


# ── Submit assignment ─────────────────────────────────────────────────────────


class SubmitAnnotationView(LoginRequiredMixin, View):
    def post(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_annotation_assignment(document, request.user)

        if assignment.status in {
            Assignment.STATUS_ASSIGNED,
            Assignment.STATUS_IN_PROGRESS,
            Assignment.STATUS_RETURNED,
        }:
            graph = _get_user_graph_or_404(document, request.user, assignment)
            valid, validation_messages = validate_graph_data(
                serialize_graph(graph), graph.schema_version.linkml_yaml
            )
            if not valid:
                messages.warning(
                    request,
                    "Submission blocked: schema validation errors must be resolved first.",
                )
                for message in validation_messages[:5]:
                    messages.warning(request, message)
                return redirect("my-queue")

        # Close all open sessions
        for s in WorkSession.objects.filter(
            assignment=assignment, ended_at__isnull=True
        ):
            close_session(s)

        submittable = {
            Assignment.STATUS_ASSIGNED,
            Assignment.STATUS_IN_PROGRESS,
            Assignment.STATUS_RETURNED,
        }
        if assignment.status in submittable:
            old_status = assignment.status
            assignment.status = Assignment.STATUS_SUBMITTED
            assignment.save(update_fields=["status"])
            emit_audit(
                request.user,
                "assignment.submit",
                "Assignment",
                assignment.pk,
                {"from": old_status, "to": assignment.status},
            )
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
        if m.role not in (
            ProjectMembership.ROLE_REVIEWER,
            ProjectMembership.ROLE_ADMIN,
        ):
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
                WorkSession.objects.filter(assignment=assignment).aggregate(
                    Sum("active_seconds")
                )["active_seconds__sum"]
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

        is_admin = (
            request.user.is_superuser
            or ProjectMembership.objects.filter(
                project=project, user=request.user, role=ProjectMembership.ROLE_ADMIN
            ).exists()
        )

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


class ReturnAssignmentView(LoginRequiredMixin, View):
    """Return submitted work to its annotator for further editing."""

    def post(self, request, pk, doc_pk, assignment_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_reviewer_or_admin(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = get_object_or_404(
            Assignment,
            pk=assignment_pk,
            project=project,
            document=document,
        )

        if assignment.status == Assignment.STATUS_SUBMITTED:
            assignment.status = Assignment.STATUS_RETURNED
            assignment.save(update_fields=["status"])
            emit_audit(
                request.user,
                "assignment.return",
                "Assignment",
                assignment.pk,
                {
                    "from": Assignment.STATUS_SUBMITTED,
                    "to": Assignment.STATUS_RETURNED,
                },
            )
            messages.success(
                request,
                f"Returned the assignment to {assignment.annotator.username}.",
            )
        else:
            messages.info(
                request,
                "Only submitted assignments can be returned for editing.",
            )

        return redirect("review-document", pk=project.pk, doc_pk=document.pk)


class AdjudicateEdgeView(LoginRequiredMixin, View):
    """POST: reviewer advances a specific graph's edge (complete→reviewed or reviewed→gold)."""

    def post(self, request, pk, doc_pk, graph_pk, edge_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_reviewer_or_admin(request, project)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        graph = get_object_or_404(CausalGraph, pk=graph_pk, document=document)
        edge = get_object_or_404(Edge, pk=edge_pk, graph=graph)

        adjudicate_edge(edge, request.user)

        return redirect("review-document", pk=pk, doc_pk=doc_pk)


# ── Schema demo (Phase 2 acceptance helper) ───────────────────────────────────


class SchemaDemoView(LoginRequiredMixin, View):
    def get(self, request):
        schema_version, lsv = _get_active_schema()
        if not lsv:
            return render(
                request, "annotation/schema_demo.html", {"schema_version": None}
            )

        ui = _load_ui_config()
        edge_spec = _edge_form_spec(lsv, ui)
        node_spec = _node_form_spec(lsv)

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


# ── GeoNames lookup endpoint ─────────────────────────────────────────────────────


class GeoNamesLookupView(LoginRequiredMixin, View):
    """Look up country/state from coordinates using GeoNames API."""

    def get(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        require_editable_assignment(document, request.user)

        latitude = request.GET.get("latitude")
        longitude = request.GET.get("longitude")

        if not latitude or not longitude:
            return JsonResponse(
                {"error": "latitude and longitude parameters are required"}, status=400
            )

        try:
            lat = float(latitude)
            lon = float(longitude)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Invalid coordinates"}, status=400)

        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return JsonResponse({"error": "Coordinates out of range"}, status=400)

        from apps.annotation.utils import get_geographic_context

        username = (
            request.GET.get("username")
            or request.session.get("geonames_username")
            or settings.GEONAMES_USERNAME
            or None
        )
        geo = get_geographic_context(lat, lon, username)

        return JsonResponse(geo)


# ── Auto-save endpoint ───────────────────────────────────────────────────────────


class AutoSaveView(LoginRequiredMixin, View):
    """Auto-save annotation form data via PATCH requests."""

    def patch(self, request, pk, doc_pk, annotation_type, annotation_id=None):
        """Save a single field update without reloading the full form."""
        project = get_object_or_404(Project, pk=pk)
        document = get_object_or_404(Document, pk=doc_pk, project=project)
        assignment = require_editable_assignment(document, request.user)
        graph = _get_user_graph_or_404(document, request.user, assignment)

        if not _is_htmx(request):
            return JsonResponse({"error": "Only HTMX requests allowed"}, status=400)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if not isinstance(data, dict):
            return JsonResponse(
                {"error": "Request body must be a JSON object"}, status=400
            )

        if annotation_type == "node":
            from django.utils import timezone

            node = get_object_or_404(Node, pk=annotation_id, graph=graph)
            node.data = {**node.data, **data}
            node.save(update_fields=["data"])
            return JsonResponse({"ok": True, "last_saved": timezone.now().isoformat()})

        elif annotation_type == "edge":
            edge = get_object_or_404(Edge, pk=annotation_id, graph=graph)
            edge.data = {**edge.data, **data}
            edge.save(update_fields=["data"])
            return JsonResponse({"ok": True, "last_saved": edge.updated_at.isoformat()})

        return JsonResponse({"error": "Invalid annotation type"}, status=400)
