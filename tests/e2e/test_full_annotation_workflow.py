"""End-to-end schema-agnosticism smoke test.

Walks the complete annotator journey — schema upload/activation, ontology
upload, project/document/assignment setup, annotation, export, and LinkML
validation — against a hand-written, non-CAMO-vocabulary LinkML schema
(tests/fixtures/toy_schema.yaml). If Loom's forms, validation, or export ever
regress into naming a CAMO slot directly (see CLAUDE.md's "one defining
constraint"), this test is where that would show up, since the toy schema's
slots (name/description/strength/source_text/confidence) share no vocabulary
with CAMO's (entity_type/claim_strength/philosophical_account/...).

Uses Django's TestClient only — no Playwright/browser automation.
"""

from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.annotation.models import CausalGraph, Edge, Node
from apps.export.serializer import serialize_graph
from apps.export.validators import validate_graph_data
from apps.ontology.models import OntologyRelease
from apps.projects.models import Document, Project, ProjectMembership
from apps.projects.services import assign_document
from apps.schemas.models import SchemaVersion

TOY_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "toy_schema.yaml"
)

TOY_OBO = b"""\
format-version: 1.2
ontology: toy

[Term]
id: TOY:0000001
name: increases

[Term]
id: TOY:0000002
name: decreases

[Term]
id: TOY:0000003
name: causes
"""


@pytest.mark.django_db
def test_full_annotation_workflow_on_non_camo_schema():
    User = get_user_model()
    admin = User.objects.create_superuser(
        "e2e-admin", "e2e-admin@test.example", "password"
    )
    annotator = User.objects.create_user("e2e-annotator", password="password")

    client = Client()
    client.force_login(admin)

    # 1. Admin uploads the toy schema.
    schema_yaml = TOY_SCHEMA_PATH.read_text(encoding="utf-8")
    upload = SimpleUploadedFile(
        "toy_schema.yaml",
        schema_yaml.encode("utf-8"),
        content_type="application/x-yaml",
    )
    response = client.post(reverse("schema-upload"), {"schema_file": upload})
    assert response.status_code == 302
    assert SchemaVersion.objects.count() == 1
    schema = SchemaVersion.objects.get()

    # 2. Admin activates the schema.
    response = client.post(reverse("schema-activate", args=[schema.pk]))
    assert response.status_code == 302
    schema.refresh_from_db()
    assert schema.is_active is True

    # 3. Admin uploads a toy ontology.
    obo_upload = SimpleUploadedFile(
        "toy_ontology.obo", TOY_OBO, content_type="text/plain"
    )
    response = client.post(
        reverse("ontology-manage-upload"),
        {"name": "toy-ontology", "prefix": "TOY", "source_file": obo_upload},
    )
    assert response.status_code == 200
    release = OntologyRelease.objects.get(name="toy-ontology")
    assert release.term_count > 0

    # 4. Admin creates a Project pinned to the toy schema.
    project = Project.objects.create(
        name="Toy E2E Project", created_by=admin, active_schema=schema
    )
    ProjectMembership.objects.create(
        project=project, user=admin, role=ProjectMembership.ROLE_ADMIN
    )
    ProjectMembership.objects.create(
        project=project, user=annotator, role=ProjectMembership.ROLE_ANNOTATOR
    )

    # 5. Admin creates a Document and assigns it to the annotator.
    document = Document.objects.create(
        project=project,
        source=Document.SOURCE_MANUAL,
        title="Toy Paper",
        canonical_text="Wolves reduce deer populations in Yellowstone.",
    )
    assign_document(project, document, annotator, admin)

    # 6. Annotator opens the annotation workspace, then the edge form panel —
    # the toy schema's own slot names must appear in the rendered edge form,
    # proving the form is built from the active schema, not from any
    # hardcoded CAMO field list. (The edge form is an HTMX-loaded fragment,
    # not part of the initial workspace page, so it's fetched separately.)
    client.force_login(annotator)
    response = client.get(
        reverse("annotate", kwargs={"pk": project.pk, "doc_pk": document.pk})
    )
    assert response.status_code == 200

    response = client.get(
        reverse("edge-form", kwargs={"pk": project.pk, "doc_pk": document.pk})
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert 'name="strength"' in body
    assert 'name="confidence"' in body

    graph = CausalGraph.objects.get(document=document, annotator=annotator)

    # 7. Annotator creates subject and object nodes.
    response = client.post(
        reverse("node-create", kwargs={"pk": project.pk, "doc_pk": document.pk}),
        {"name": "Wolves", "description": "Grey wolf population"},
    )
    assert response.status_code == 302
    response = client.post(
        reverse("node-create", kwargs={"pk": project.pk, "doc_pk": document.pk}),
        {"name": "Deer", "description": "Deer population"},
    )
    assert response.status_code == 302
    assert Node.objects.filter(graph=graph).count() == 2
    subject = Node.objects.get(graph=graph, name="Wolves")
    obj = Node.objects.get(graph=graph, name="Deer")

    # 8. Annotator creates an edge linking subject -> object.
    response = client.post(
        reverse("edge-create", kwargs={"pk": project.pk, "doc_pk": document.pk}),
        {
            "subject": subject.node_id,
            "object": obj.node_id,
            "name": "Wolves reduce deer",
            "strength": "strong",
            "source_text": "Wolves reduce deer populations in Yellowstone.",
            "confidence": "0.8",
        },
    )
    assert response.status_code == 302
    assert Edge.objects.filter(graph=graph).count() == 1
    edge = Edge.objects.get(graph=graph)
    assert edge.status == Edge.STATUS_DRAFT

    # 9. Export and validate the graph against the (non-CAMO) toy schema.
    data = serialize_graph(graph)
    is_valid, validation_messages = validate_graph_data(data, schema.linkml_yaml)
    assert is_valid, validation_messages
