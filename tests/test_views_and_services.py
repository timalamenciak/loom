"""Focused branch coverage for service boundaries and smaller Django views."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import Http404, HttpResponse
from django.urls import reverse

from apps.annotation.models import CausalGraph, Edge, Node
from apps.annotation.services import (
    create_edge,
    create_node,
    delete_node,
    set_edge_source_spans,
    set_node_source_spans,
    update_edge,
    update_node,
)
from apps.audit.models import AuditEvent
from apps.documents.models import TextSpan
from apps.documents.services import (
    ensure_canonical_text,
    extract_text_from_pdf,
    pdf_text_needs_extraction,
)
from apps.projects.models import Assignment, Document, Project, ProjectMembership
from apps.schemas.models import SchemaVersion
from apps.schemas.services import (
    get_or_create_schema_version,
    load_schema_path,
    validate_schema_yaml,
)

CAMO_SCHEMA = """\
id: https://example.org/camo
name: camo
version: 9.0.0
prefixes:
  camo: https://example.org/camo/
default_prefix: camo
classes:
  CausalGraph:
  CausalNode:
    attributes:
      name:
        range: string
  CausalEdge:
    attributes:
      predicate:
        range: string
"""


@pytest.fixture
def workspace(db):
    user = get_user_model().objects.create_user("branch-user")
    other = get_user_model().objects.create_user("branch-other")
    project = Project.objects.create(name="Branch project", created_by=user)
    ProjectMembership.objects.create(
        project=project, user=user, role=ProjectMembership.ROLE_ANNOTATOR
    )
    schema = SchemaVersion.objects.create(
        version="9.0.0", linkml_yaml=CAMO_SCHEMA, is_active=True
    )
    project.active_schema = schema
    project.save(update_fields=["active_schema"])
    document = Document.objects.create(
        project=project,
        source=Document.SOURCE_MANUAL,
        title="Branch paper",
        abstract="Abstract text",
        canonical_text="Alpha causes beta.",
        page_map=[],
    )
    assignment = Assignment.objects.create(
        project=project,
        document=document,
        annotator=user,
        assigned_by=user,
        status=Assignment.STATUS_IN_PROGRESS,
    )
    graph = CausalGraph.objects.create(
        document=document, annotator=user, schema_version=schema
    )
    assignment.graph = graph
    assignment.save(update_fields=["graph"])
    first = Node.objects.create(
        graph=graph,
        node_id="first",
        name="Alpha",
        data={"name": "Alpha"},
        schema_version=schema,
    )
    second = Node.objects.create(
        graph=graph,
        node_id="second",
        name="Beta",
        data={"name": "Beta"},
        schema_version=schema,
    )
    edge = Edge.objects.create(
        graph=graph,
        edge_id="edge",
        subject=first,
        object=second,
        predicate="causes",
        data={"predicate": "causes"},
        schema_version=schema,
    )
    return SimpleNamespace(
        user=user,
        other=other,
        project=project,
        schema=schema,
        document=document,
        assignment=assignment,
        graph=graph,
        first=first,
        second=second,
        edge=edge,
    )


def test_schema_services_validate_deduplicate_load_and_reject(tmp_path, db):
    document = validate_schema_yaml(CAMO_SCHEMA)
    assert document["version"] == "9.0.0"
    schema, created = get_or_create_schema_version(CAMO_SCHEMA)
    same, created_again = get_or_create_schema_version(CAMO_SCHEMA)
    assert created and not created_again and same == schema

    path = tmp_path / "camo.yaml"
    path.write_text(CAMO_SCHEMA, encoding="utf-8")
    loaded, created = load_schema_path(path, version="renamed", activate=True)
    assert not created
    assert loaded.version == "renamed"
    assert loaded.is_active

    with pytest.raises(ValueError, match="mapping"):
        validate_schema_yaml("- item")
    with pytest.raises(ValueError, match="External schema imports"):
        validate_schema_yaml(CAMO_SCHEMA + "imports: [remote:schema]\n")
    with pytest.raises(ValueError, match="missing required classes"):
        validate_schema_yaml(CAMO_SCHEMA.split("  CausalEdge:", 1)[0])
    with pytest.raises(ValueError, match="Invalid YAML"):
        validate_schema_yaml("[")


def test_schema_views_enforce_superuser_and_activate(client, workspace):
    client.force_login(workspace.user)
    for name, args in (
        ("schema-list", ()),
        ("schema-detail", (workspace.schema.pk,)),
    ):
        assert client.get(reverse(name, args=args)).status_code == 403
    assert (
        client.post(reverse("schema-activate", args=[workspace.schema.pk])).status_code
        == 403
    )

    admin = get_user_model().objects.create_superuser("schema-admin")
    client.force_login(admin)
    assert client.get(reverse("schema-list")).status_code == 200
    with patch("apps.schemas.views.get_schema_view") as get_view:
        get_view.return_value.form_spec.return_value = []
        get_view.return_value.class_names.return_value = ["CausalEdge"]
        assert (
            client.get(reverse("schema-detail", args=[workspace.schema.pk])).status_code
            == 200
        )
    assert (
        client.post(reverse("schema-activate", args=[workspace.schema.pk])).status_code
        == 302
    )


def test_document_extraction_and_fallback_branches(workspace):
    document = workspace.document
    document.pdf_file = "pdfs/fake.pdf"
    document.canonical_text = ""
    assert pdf_text_needs_extraction(document)

    pages = [
        SimpleNamespace(extract_text=lambda: "Page one"),
        SimpleNamespace(extract_text=lambda: None),
    ]
    opened = MagicMock()
    opened.__enter__.return_value.pages = pages
    with patch("pdfplumber.open", return_value=opened):
        assert extract_text_from_pdf(document)
    assert document.canonical_text == "Page one\n"
    assert document.page_map[-1]["page"] == 2

    with patch("pdfplumber.open", side_effect=OSError("broken")):
        assert not extract_text_from_pdf(document)

    document.pdf_file = None
    assert not extract_text_from_pdf(document)
    document.canonical_text = ""
    assert ensure_canonical_text(document)
    assert document.canonical_text == document.abstract
    document.abstract = ""
    document.canonical_text = ""
    assert not ensure_canonical_text(document)


def test_document_reader_pdf_and_span_htmx_paths(client, workspace, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(workspace.user)
    read_url = reverse("document-read", args=[workspace.document.pk])
    assert client.get(read_url).status_code == 200

    pdf_url = reverse("document-pdf", args=[workspace.document.pk])
    with pytest.raises(Http404):
        from apps.documents.views import DocumentPdfView

        request = MagicMock(user=workspace.user)
        DocumentPdfView().get(request, workspace.document.pk)

    workspace.document.pdf_file.save("paper.pdf", ContentFile(b"%PDF-1.4 test"))
    response = client.get(pdf_url)
    assert response.status_code == 200
    assert response["Content-Disposition"] == 'inline; filename="paper.pdf"'
    assert b"%PDF-1.4" in b"".join(response.streaming_content)

    create_url = reverse("span-create", args=[workspace.document.pk])
    bad = client.post(create_url, {"start_char": "bad", "end_char": 2})
    assert bad.status_code == 302
    out_of_range = client.post(create_url, {"start_char": 0, "end_char": 999})
    assert out_of_range.status_code == 302

    partial = client.post(
        create_url,
        {"start_char": 0, "end_char": 5},
        HTTP_HX_REQUEST="true",
    )
    assert partial.status_code == 200
    selected = client.post(
        create_url,
        {"start_char": 6, "end_char": 12},
        HTTP_HX_REQUEST="true",
        HTTP_X_SPAN_SELECT="true",
    )
    assert selected.status_code == 200
    assert selected.json()["excerpt_bin_html"]

    span = TextSpan.objects.filter(created_by=workspace.user).first()
    delete_url = reverse("span-delete", args=[workspace.document.pk, span.pk])
    assert client.post(delete_url, HTTP_HX_REQUEST="true").status_code == 200
    remaining = TextSpan.objects.filter(created_by=workspace.user).first()
    excerpt_url = (
        reverse("span-delete", args=[workspace.document.pk, remaining.pk])
        + "?surface=excerpt-bin"
    )
    assert client.post(excerpt_url, HTTP_HX_REQUEST="true").status_code == 200


def test_document_member_and_missing_file_permissions(client, workspace):
    from apps.documents.views import _require_member

    request = SimpleNamespace(user=workspace.other)
    with pytest.raises(PermissionDenied):
        _require_member(request, workspace.document)
    workspace.other.is_superuser = True
    _require_member(request, workspace.document)

    client.force_login(workspace.user)
    workspace.document.pdf_file = "pdfs/missing.pdf"
    workspace.document.save(update_fields=["pdf_file"])
    assert (
        client.get(reverse("document-pdf", args=[workspace.document.pk])).status_code
        == 404
    )


def test_annotation_services_reject_cross_graph_endpoints_and_audit(workspace):
    other_graph = CausalGraph.objects.create(
        document=workspace.document,
        annotator=workspace.other,
        schema_version=workspace.schema,
    )
    outsider = Node.objects.create(
        graph=other_graph,
        name="Outsider",
        data={},
        schema_version=workspace.schema,
    )
    with pytest.raises(ValueError, match="endpoints"):
        create_edge(workspace.graph, workspace.first, outsider, {})
    with pytest.raises(ValueError, match="subject"):
        update_edge(workspace.edge, {}, subject=outsider)
    with pytest.raises(ValueError, match="object"):
        update_edge(workspace.edge, {}, object_node=outsider)

    node = create_node(
        workspace.graph,
        {"entity_type": "biotic", "entity_term": "oak"},
        actor=workspace.user,
    )
    assert node.name == "biotic — oak"
    update_node(node, {"name": "  Renamed  "}, actor=workspace.user)
    assert node.name == "Renamed"

    connected = create_edge(
        workspace.graph,
        node,
        workspace.second,
        {"predicate": "affects"},
        actor=workspace.user,
    )
    delete_node(node, workspace.user)
    assert not Edge.objects.filter(pk=connected.pk).exists()
    assert AuditEvent.objects.filter(action="edge.delete").exists()


def test_annotation_span_linking_does_not_steal_grounding(workspace):
    span_one = TextSpan.objects.create(
        document=workspace.document,
        start_char=0,
        end_char=5,
        text="Alpha",
        created_by=workspace.user,
        node=workspace.first,
        edge=workspace.edge,
    )
    span_two = TextSpan.objects.create(
        document=workspace.document,
        start_char=6,
        end_char=12,
        text="causes",
        created_by=workspace.user,
    )
    occupied = TextSpan.objects.create(
        document=workspace.document,
        start_char=13,
        end_char=17,
        text="beta",
        created_by=workspace.user,
        node=workspace.second,
    )

    set_node_source_spans(workspace.first, [span_two, occupied], actor=workspace.user)
    span_one.refresh_from_db()
    span_two.refresh_from_db()
    occupied.refresh_from_db()
    assert span_one.node is None
    assert span_two.node == workspace.first
    assert occupied.node == workspace.second

    set_edge_source_spans(workspace.edge, [span_two], actor=workspace.user)
    span_one.refresh_from_db()
    span_two.refresh_from_db()
    assert span_one.edge is None
    assert span_two.edge == workspace.edge


class FakeSchemaView:
    def __init__(self, data=None, valid=True):
        self.data = data or {}
        self.valid = valid

    def form_spec(self, *args, **kwargs):
        return []

    def bind_form_data(self, *args, **kwargs):
        return SimpleNamespace(
            is_valid=self.valid,
            data=self.data,
            errors={} if self.valid else {"name": ["required"]},
        )


def test_annotation_form_get_edit_advance_and_legacy_views(client, workspace):
    client.force_login(workspace.user)
    prefix = [workspace.project.pk, workspace.document.pk]
    fake = FakeSchemaView()
    render_response = HttpResponse("rendered")
    with (
        patch("apps.annotation.views.get_schema_view", return_value=fake),
        patch("apps.annotation.views.render", return_value=render_response),
    ):
        urls = [
            reverse("graph-panel", args=prefix),
            reverse("node-form", args=prefix) + "?span_pk=1",
            reverse("node-edit", args=prefix + [workspace.first.pk]),
            reverse("edge-form", args=prefix),
            reverse("edge-edit", args=prefix + [workspace.edge.pk]),
        ]
        assert all(client.get(url).status_code == 200 for url in urls)

    advance = reverse("edge-advance", args=prefix + [workspace.edge.pk])
    assert client.post(advance).status_code == 302
    workspace.edge.refresh_from_db()
    assert workspace.edge.status == Edge.STATUS_COMPLETE
    assert client.post(advance, HTTP_HX_REQUEST="true").status_code == 200

    legacy = reverse("graph-view", args=prefix)
    assert client.get(legacy).status_code == 302
    assert client.post(legacy).status_code == 302


def test_annotation_node_and_edge_edit_valid_and_invalid(client, workspace):
    client.force_login(workspace.user)
    prefix = [workspace.project.pk, workspace.document.pk]
    node_url = reverse("node-edit", args=prefix + [workspace.first.pk])
    edge_url = reverse("edge-edit", args=prefix + [workspace.edge.pk])

    with patch(
        "apps.annotation.views.get_schema_view",
        return_value=FakeSchemaView({"name": "Changed", "entity_type": "biotic"}),
    ):
        assert client.post(node_url, {"name": "Changed"}).status_code == 302
    workspace.first.refresh_from_db()
    assert workspace.first.name == "Changed"

    with (
        patch(
            "apps.annotation.views.get_schema_view",
            return_value=FakeSchemaView(valid=False),
        ),
        patch(
            "apps.annotation.views.render",
            side_effect=lambda *args, **kwargs: HttpResponse(
                "errors", status=kwargs.get("status", 200)
            ),
        ),
    ):
        assert client.post(node_url, {"name": ""}).status_code == 422

    edge_data = {"predicate": "prevents", "claim_strength": "strong"}
    with patch(
        "apps.annotation.views.get_schema_view",
        return_value=FakeSchemaView(edge_data),
    ):
        response = client.post(
            edge_url,
            {
                "subject": workspace.second.node_id,
                "object": workspace.first.node_id,
                "predicate": "prevents",
            },
        )
    assert response.status_code == 302
    workspace.edge.refresh_from_db()
    assert workspace.edge.subject == workspace.second
    assert workspace.edge.object == workspace.first

    with (
        patch(
            "apps.annotation.views.get_schema_view",
            return_value=FakeSchemaView(valid=False),
        ),
        patch(
            "apps.annotation.views.render",
            side_effect=lambda *args, **kwargs: HttpResponse(
                "errors", status=kwargs.get("status", 200)
            ),
        ),
    ):
        response = client.post(
            edge_url,
            {"subject": workspace.second.node_id, "object": ""},
        )
    assert response.status_code == 422


def test_annotation_no_schema_form_responses(client, workspace):
    client.force_login(workspace.user)
    prefix = [workspace.project.pk, workspace.document.pk]
    with patch("apps.annotation.views.get_schema_view", return_value=None):
        assert client.get(reverse("node-form", args=prefix)).status_code == 200
        assert (
            client.get(
                reverse("node-edit", args=prefix + [workspace.first.pk])
            ).status_code
            == 200
        )
        assert client.get(reverse("edge-form", args=prefix)).status_code == 200
        assert (
            client.get(
                reverse("edge-edit", args=prefix + [workspace.edge.pk])
            ).status_code
            == 200
        )


def test_annotation_helper_error_and_schema_demo_paths(client, workspace, settings):
    from apps.annotation import views

    assert views._parse_span_ids(["1, 2", "bad", "2", "-1"]) == [1, 2]
    with patch.object(Path, "open", side_effect=FileNotFoundError):
        assert views._load_ui_config() == {}
    SchemaVersion.objects.update(is_active=False)
    assert views._get_active_schema() == (None, None)

    client.force_login(workspace.user)
    with patch("apps.annotation.views._get_active_schema", return_value=(None, None)):
        assert client.get(reverse("schema-demo")).status_code == 200
    with (
        patch(
            "apps.annotation.views._get_active_schema",
            return_value=(workspace.schema, MagicMock()),
        ),
        patch("apps.annotation.views.render", return_value=HttpResponse("demo")),
    ):
        assert client.get(reverse("schema-demo")).status_code == 200


def test_project_model_fallbacks_and_display_values(workspace):
    document = workspace.document
    assert workspace.project.member_role(workspace.other) is None
    membership = workspace.project.memberships.get(user=workspace.user)
    assert workspace.user.username in str(membership)
    assert str(document) == document.title

    document.pdf_file = "pdfs/paper.pdf"
    assert document.text_source == "pdf"
    document.pdf_file = None
    document.authors = ["One"]
    assert document.short_authors == "One"
    document.authors = ["One", "Two"]
    assert document.short_authors == "One & Two"
    document.authors = ["One", "Two", "Three"]
    assert document.short_authors == "One et al."
    assert workspace.user.username in str(workspace.assignment)


def test_llm_app_config_remains_installable():
    import apps.llm as llm_module
    from apps.llm.apps import LlmConfig

    config = LlmConfig("apps.llm", llm_module)
    assert config.name == "apps.llm"
    assert config.label == "llm"


def test_submit_refuses_invalid_graph_and_reports_terminal_assignment(
    client, workspace
):
    client.force_login(workspace.user)
    submit_url = reverse(
        "submit-annotation", args=[workspace.project.pk, workspace.document.pk]
    )
    with (
        patch("apps.annotation.views.serialize_graph", return_value={}),
        patch(
            "apps.annotation.views.validate_graph_data",
            return_value=(False, ["missing predicate"]),
        ),
    ):
        assert client.post(submit_url).status_code == 302
    workspace.assignment.refresh_from_db()
    assert workspace.assignment.status == Assignment.STATUS_IN_PROGRESS

    workspace.assignment.status = Assignment.STATUS_SUBMITTED
    workspace.assignment.save(update_fields=["status"])
    assert client.post(submit_url).status_code == 302
