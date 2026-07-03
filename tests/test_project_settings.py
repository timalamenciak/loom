import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.annotation.services import create_edge, create_graph, create_node
from apps.audit.models import AuditEvent
from apps.ontology.models import (
    OntologyLoadItem,
    OntologyLoadRequest,
    OntologySnapshot,
    OntologyTerm,
)
from apps.projects.models import Assignment, Document, Project, ProjectMembership
from apps.schemas.models import SchemaVersion
from apps.schemas.ontology_inference import infer_ontologies
from tests.schema_fixtures import frozen_schema_path

User = get_user_model()
# Pinned to 0.4.1 deliberately: covers the inline-attributes declaration style
# and gives `test_existing_graph_keeps_pinned_schema` a distinct "older" schema
# to upgrade from. See conftest.frozen_schema_042 for the "newer" half.
SCHEMA_PATH = frozen_schema_path("0.4.1")


@pytest.fixture
def owner(db):
    return User.objects.create_user("project-owner", password="password")


@pytest.fixture
def schema(db):
    return SchemaVersion.objects.create(
        version="0.4.1",
        linkml_yaml=SCHEMA_PATH.read_text(encoding="utf-8"),
        is_active=True,
    )


@pytest.fixture
def configured_project(owner, schema):
    project = Project.objects.create(
        name="Settings Test",
        created_by=owner,
        active_schema=schema,
    )
    ProjectMembership.objects.create(project=project, user=owner, role="admin")
    return project


@pytest.mark.django_db
def test_inference_finds_registered_and_unresolved_prefixes(schema):
    result = infer_ontologies(schema)
    names = {item["name"] for item in result["matched"]}
    unresolved = {item["prefix"] for item in result["unresolved"]}
    assert {"envo", "elmo", "pato", "eco", "bfo"} <= names
    # ncbitaxon is no longer a registered ontology (Wikidata is now canonical
    # for taxa) — it still declares a namespace in this frozen 0.4.1 schema,
    # so it correctly falls into unresolved rather than matched.
    assert {"obi", "sepio", "ncbitaxon"} <= unresolved


@pytest.mark.django_db
def test_inference_uses_loom_ontology_annotations():
    schema = SchemaVersion.objects.create(
        version="loom-ontologies",
        linkml_yaml="""
id: https://example.org/loom-ontologies
name: loom-ontologies
classes:
  Example:
    attributes:
      term:
        range: uriorcurie
        annotations:
          loom_ontologies: "PATO, ELMO"
""",
    )

    result = infer_ontologies(schema)
    names = {item["name"] for item in result["matched"]}

    assert {"pato", "elmo"} <= names


@pytest.mark.django_db
def test_owner_can_update_project_settings(client, owner, configured_project, schema):
    client.force_login(owner)
    response = client.post(
        reverse("project-settings", args=[configured_project.pk]),
        {
            "name": "Renamed project",
            "description": "Updated",
            "active_schema": schema.pk,
            "ontology_names": [],
        },
    )
    assert response.status_code == 302
    configured_project.refresh_from_db()
    assert configured_project.name == "Renamed project"
    assert AuditEvent.objects.filter(
        action="project.settings.update", target_id=str(configured_project.pk)
    ).exists()


@pytest.mark.django_db
def test_owner_can_upload_and_pin_schema(client, owner, configured_project):
    content = frozen_schema_path("0.4.2").read_bytes()
    upload = SimpleUploadedFile("camo-0.4.2.yaml", content, content_type="text/yaml")
    client.force_login(owner)
    response = client.post(
        reverse("project-settings", args=[configured_project.pk]),
        {
            "name": configured_project.name,
            "description": "",
            "schema_file": upload,
            "ontology_names": [],
        },
    )
    assert response.status_code == 302
    configured_project.refresh_from_db()
    assert configured_project.active_schema.version == "0.4.2"


@pytest.mark.django_db
def test_existing_graph_keeps_pinned_schema(client, owner, configured_project, schema):
    document = Document.objects.create(
        project=configured_project,
        source=Document.SOURCE_MANUAL,
        title="Pinned graph",
        canonical_text="Evidence text.",
    )
    graph = create_graph(document, owner, schema)
    Assignment.objects.create(
        project=configured_project,
        document=document,
        annotator=owner,
        assigned_by=owner,
        graph=graph,
    )
    newer = SchemaVersion.objects.create(
        version="0.4.2",
        linkml_yaml=frozen_schema_path("0.4.2").read_text(encoding="utf-8"),
    )
    configured_project.active_schema = newer
    configured_project.save(update_fields=["active_schema"])

    client.force_login(owner)
    response = client.get(
        reverse("annotate", args=[configured_project.pk, document.pk])
    )
    assert response.status_code == 200
    assert response.context["graph"] == graph
    edge_fields = {
        slot["name"]
        for layer in response.context["edge_spec"]
        for slot in layer["slots"]
    }
    assert "biotic_interaction_type" not in edge_fields


@pytest.mark.django_db
def test_project_admin_who_is_not_owner_cannot_open_settings(
    client, configured_project
):
    admin = User.objects.create_user("other-admin", password="password")
    ProjectMembership.objects.create(
        project=configured_project, user=admin, role="admin"
    )
    client.force_login(admin)
    response = client.get(reverse("project-settings", args=[configured_project.pk]))
    assert response.status_code == 403


@pytest.mark.django_db
def test_project_settings_shows_each_ontology_load_state(
    client, owner, configured_project
):
    configured_project.ontology_names = ["envo", "pato", "go"]
    configured_project.save(update_fields=["ontology_names"])
    request = OntologyLoadRequest.objects.create(
        project=configured_project,
        requested_by=owner,
        ontology_names=["envo", "pato", "go"],
        status=OntologyLoadRequest.STATUS_RUNNING,
    )
    OntologyLoadItem.objects.create(
        request=request,
        name="envo",
        prefix="ENVO",
        status=OntologyLoadItem.STATUS_COMPLETE,
        term_count=123,
    )
    OntologyLoadItem.objects.create(
        request=request,
        name="pato",
        prefix="PATO",
        status=OntologyLoadItem.STATUS_RUNNING,
    )
    OntologyLoadItem.objects.create(
        request=request,
        name="go",
        prefix="GO",
        status=OntologyLoadItem.STATUS_FAILED,
        error="download failed",
    )

    client.force_login(owner)
    response = client.get(reverse("project-settings", args=[configured_project.pk]))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Loaded ontology status" in html
    assert "ENVO" in html and "123" in html and "Ready" in html
    assert "PATO" in html and "Loading" in html
    assert "GO" in html and "Failed" in html and "download failed" in html
    assert reverse("project-ontology-status", args=[configured_project.pk]) in html


@pytest.mark.django_db
def test_missing_ontology_registration_form_is_not_nested(
    client, owner, configured_project
):
    client.force_login(owner)
    response = client.get(reverse("project-settings", args=[configured_project.pk]))
    html = response.content.decode()
    settings_close = html.index("</form>")
    register_action = reverse("project-register-ontology", args=[configured_project.pk])

    assert html.index(register_action) > settings_close


@pytest.mark.django_db
def test_project_search_is_member_and_snapshot_scoped(
    client, owner, configured_project
):
    snapshot = OntologySnapshot.objects.create(
        name="project-snapshot",
        source_versions={"ENVO": {"name": "envo"}},
    )
    OntologyTerm.objects.create(
        snapshot=snapshot,
        prefix="ENVO",
        curie="ENVO:00001001",
        label="temperate biome",
    )
    configured_project.ontology_snapshot = snapshot
    configured_project.ontology_names = ["envo"]
    configured_project.save(update_fields=["ontology_snapshot", "ontology_names"])

    client.force_login(owner)
    response = client.get(
        reverse("project-ontology-search", args=[configured_project.pk]),
        {"q": "temperate", "prefixes": "ENVO"},
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["curie"] == "ENVO:00001001"

    hydrated = client.get(
        reverse("project-ontology-search", args=[configured_project.pk]),
        {"curies": "ENVO:00001001", "prefixes": "ENVO"},
    ).json()
    assert hydrated["results"][0]["label"] == "temperate biome"
    assert hydrated["meta"]["status"] == "ready"

    stranger = User.objects.create_user("settings-stranger", password="password")
    client.force_login(stranger)
    denied = client.get(
        reverse("project-ontology-search", args=[configured_project.pk]),
        {"q": "temperate"},
    )
    assert denied.status_code == 403


@pytest.mark.django_db
def test_owner_can_delete_populated_project(client, owner, configured_project, schema):
    document = Document.objects.create(
        project=configured_project,
        source=Document.SOURCE_MANUAL,
        title="Deletion paper",
    )
    graph = create_graph(document, owner, schema)
    subject = create_node(graph, {"name": "Subject"})
    object_node = create_node(graph, {"name": "Object"})
    create_edge(graph, subject, object_node, {"predicate": "regulates"})
    project_pk = configured_project.pk

    client.force_login(owner)
    response = client.post(
        reverse("project-delete", args=[project_pk]),
        {"confirmation": configured_project.name},
    )
    assert response.status_code == 302
    assert not Project.objects.filter(pk=project_pk).exists()
    assert AuditEvent.objects.filter(
        action="project.delete", target_id=str(project_pk)
    ).exists()


@pytest.mark.django_db
def test_delete_requires_exact_project_name(client, owner, configured_project):
    client.force_login(owner)
    response = client.post(
        reverse("project-delete", args=[configured_project.pk]),
        {"confirmation": "wrong"},
    )
    assert response.status_code == 200
    assert Project.objects.filter(pk=configured_project.pk).exists()
