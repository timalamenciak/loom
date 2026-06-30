"""Regression tests for Loom's operator-facing management commands."""

from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.annotation.models import CausalGraph, Edge, Node
from apps.ontology.models import OntologySnapshot
from apps.projects.models import Document, Project, ProjectMembership
from apps.schemas.models import SchemaVersion

MINIMAL_SCHEMA = """\
id: https://example.org/test
name: test
version: 1.2.3
prefixes:
  test: https://example.org/test/
default_prefix: test
classes:
  Thing:
    attributes:
      name:
        range: string
"""


@pytest.fixture
def operator(db):
    return get_user_model().objects.create_user("operator")


@pytest.fixture
def project(operator):
    project = Project.objects.create(name="Command project", created_by=operator)
    ProjectMembership.objects.create(
        project=project,
        user=operator,
        role=ProjectMembership.ROLE_ADMIN,
    )
    return project


@pytest.fixture
def graph(project, operator):
    schema = SchemaVersion.objects.create(
        version="old", linkml_yaml=MINIMAL_SCHEMA, is_active=True
    )
    document = Document.objects.create(
        project=project,
        source=Document.SOURCE_MANUAL,
        title="A command-tested article",
        canonical_text="A affects B.",
    )
    graph = CausalGraph.objects.create(
        document=document,
        annotator=operator,
        schema_version=schema,
    )
    subject = Node.objects.create(
        graph=graph,
        name="A",
        data={"removed": "node value"},
        schema_version=schema,
    )
    object_node = Node.objects.create(
        graph=graph,
        name="B",
        data={},
        schema_version=schema,
    )
    Edge.objects.create(
        graph=graph,
        subject=subject,
        object=object_node,
        predicate="affects",
        data={"removed": "edge value"},
        schema_version=schema,
    )
    return graph


def test_load_and_list_schema_commands(db, tmp_path):
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(MINIMAL_SCHEMA, encoding="utf-8")
    output = StringIO()

    call_command("load_schema", schema_path, "--activate", stdout=output)

    loaded = SchemaVersion.objects.get()
    assert loaded.version == "1.2.3"
    assert loaded.is_active
    assert "Loaded CAMO 1.2.3" in output.getvalue()

    output = StringIO()
    call_command("list_schemas", stdout=output)
    assert "[ACTIVE]" in output.getvalue()


def test_load_schema_override_fallback_and_errors(db, tmp_path):
    missing = tmp_path / "missing.yaml"
    with pytest.raises(CommandError, match="File not found"):
        call_command("load_schema", missing)

    malformed = tmp_path / "odd.yaml"
    malformed.write_text("[", encoding="utf-8")
    with patch(
        "linkml_runtime.utils.schemaview.SchemaView", side_effect=ValueError("bad")
    ):
        with pytest.raises(CommandError, match="Invalid LinkML schema"):
            call_command("load_schema", malformed)

    fallback = tmp_path / "fallback.yaml"
    fallback.write_text(
        MINIMAL_SCHEMA.replace("version: 1.2.3\n", ""), encoding="utf-8"
    )
    call_command("load_schema", fallback, "--schema-version", "custom")
    assert SchemaVersion.objects.get().version == "custom"


def test_list_schemas_empty(db):
    output = StringIO()
    call_command("list_schemas", stdout=output)
    assert "No schemas loaded" in output.getvalue()


def test_create_project_command_pins_active_configuration(operator):
    schema = SchemaVersion.objects.create(
        version="active", linkml_yaml=MINIMAL_SCHEMA, is_active=True
    )
    snapshot = OntologySnapshot.objects.create(
        name="active",
        is_active=True,
        source_versions={"ENVO": {"name": "envo"}, "PATO": {}},
    )
    output = StringIO()

    call_command(
        "create_project",
        "Created by command",
        "--admin",
        operator.username,
        "--description",
        "Description",
        stdout=output,
    )

    project = Project.objects.get(name="Created by command")
    assert project.active_schema == schema
    assert project.ontology_snapshot == snapshot
    assert project.ontology_names == ["envo", "pato"]
    assert project.member_role(operator) == ProjectMembership.ROLE_ADMIN
    assert "Created project" in output.getvalue()


def test_create_project_rejects_unknown_admin(db):
    with pytest.raises(CommandError, match="No user"):
        call_command("create_project", "No owner", "--admin", "missing")


def test_import_ris_command_success_and_failures(project, tmp_path):
    ris = tmp_path / "records.ris"
    ris.write_text("TY  - JOUR\nTI  - Imported title\nER  -\n", encoding="utf-8")
    output = StringIO()
    call_command("import_ris", project.pk, ris, stdout=output)
    assert project.documents.filter(title="Imported title").exists()
    assert "Imported 1 record" in output.getvalue()

    with pytest.raises(CommandError, match="No project"):
        call_command("import_ris", 999999, ris)
    with pytest.raises(CommandError, match="File not found"):
        call_command("import_ris", project.pk, tmp_path / "absent.ris")
    with patch(
        "apps.projects.management.commands.import_ris.import_ris_file",
        side_effect=ValueError("unsafe RIS"),
    ):
        with pytest.raises(CommandError, match="unsafe RIS"):
            call_command("import_ris", project.pk, ris)


def test_attach_pdf_command_success_and_failures(project, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    document = Document.objects.create(
        project=project,
        source=Document.SOURCE_MANUAL,
        title="Needs PDF",
    )
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsmall test file")
    output = StringIO()

    with patch(
        "apps.projects.management.commands.attach_pdf.extract_pdf_text_for_document",
        return_value=True,
    ):
        call_command("attach_pdf", document.pk, pdf, stdout=output)
    document.refresh_from_db()
    assert document.has_pdf
    assert "Attached PDF" in output.getvalue()
    assert "Extracted text" in output.getvalue()

    with pytest.raises(CommandError, match="No document"):
        call_command("attach_pdf", 999999, pdf)
    with pytest.raises(CommandError, match="File not found"):
        call_command("attach_pdf", document.pk, tmp_path / "absent.pdf")


def test_extract_text_command_reports_success_failure_and_missing(project):
    document = Document.objects.create(
        project=project,
        source=Document.SOURCE_PDF_UPLOAD,
        title="Extract me",
        pdf_file="pdfs/fake.pdf",
    )
    output = StringIO()

    def extracted(doc):
        doc.canonical_text = "Extracted"
        doc.page_map = [{"page": 1}]
        return True

    with patch("apps.documents.services.extract_text_from_pdf", side_effect=extracted):
        call_command("extract_text", "--document", document.pk, stdout=output)
    assert "1/1 documents extracted" in output.getvalue()

    output = StringIO()
    with patch("apps.documents.services.extract_text_from_pdf", return_value=False):
        call_command("extract_text", "--project", project.pk, stdout=output)
    assert "extraction failed" in output.getvalue()

    with pytest.raises(CommandError, match="not found"):
        call_command("extract_text", "--document", 999999)


def test_validate_graph_command_valid_invalid_and_missing(graph):
    with pytest.raises(CommandError, match="not found"):
        call_command("validate_graph", 999999)

    output = StringIO()
    with (
        patch(
            "apps.export.management.commands.validate_graph.serialize_graph",
            return_value={},
        ),
        patch(
            "apps.export.management.commands.validate_graph.build_provenance",
            return_value={},
        ),
        patch(
            "apps.export.management.commands.validate_graph.validate_graph_data",
            return_value=(True, ["warning"]),
        ),
    ):
        call_command("validate_graph", graph.pk, stdout=output)
    assert "warning" in output.getvalue()
    assert "Valid" in output.getvalue()

    with (
        patch(
            "apps.export.management.commands.validate_graph.serialize_graph",
            return_value={},
        ),
        patch(
            "apps.export.management.commands.validate_graph.build_provenance",
            return_value={},
        ),
        patch(
            "apps.export.management.commands.validate_graph.validate_graph_data",
            return_value=(False, ["bad graph"]),
        ),
    ):
        with pytest.raises(CommandError, match="Validation failed"):
            call_command("validate_graph", graph.pk)


def test_export_graph_command_stdout_file_invalid_and_missing(graph, tmp_path):
    with pytest.raises(CommandError, match="not found"):
        call_command("export_graph", 999999)

    common = (
        patch(
            "apps.export.management.commands.export_graph.serialize_graph",
            return_value={"id": "g"},
        ),
        patch(
            "apps.export.management.commands.export_graph.build_provenance",
            return_value={"export_sha256": "a" * 64},
        ),
        patch(
            "apps.export.management.commands.export_graph.validate_graph_data",
            return_value=(True, ["non-fatal warning"]),
        ),
    )
    output = StringIO()
    errors = StringIO()
    with common[0], common[1], common[2]:
        call_command("export_graph", graph.pk, stdout=output, stderr=errors)
    assert "provenance:" in output.getvalue()
    assert "non-fatal warning" in errors.getvalue()

    destination = tmp_path / "graph.yaml"
    with (
        patch(
            "apps.export.management.commands.export_graph.serialize_graph",
            return_value={"id": "g"},
        ),
        patch(
            "apps.export.management.commands.export_graph.build_provenance",
            return_value={"export_sha256": "b" * 64},
        ),
        patch(
            "apps.export.management.commands.export_graph.validate_graph_data",
            return_value=(True, []),
        ),
    ):
        call_command("export_graph", graph.pk, "-o", destination)
    assert destination.read_text(encoding="utf-8").startswith("id: g")

    with (
        patch(
            "apps.export.management.commands.export_graph.serialize_graph",
            return_value={},
        ),
        patch(
            "apps.export.management.commands.export_graph.build_provenance",
            return_value={"export_sha256": "c" * 64},
        ),
        patch(
            "apps.export.management.commands.export_graph.validate_graph_data",
            return_value=(False, ["schema error"]),
        ),
    ):
        with pytest.raises(CommandError, match="export aborted"):
            call_command("export_graph", graph.pk)


def test_migrate_graph_command_reports_breaking_and_safe_changes(graph):
    new = SchemaVersion.objects.create(version="new", linkml_yaml=MINIMAL_SCHEMA)
    output = StringIO()
    with (
        patch(
            "apps.export.management.commands.migrate_graph._slot_names",
            side_effect=[{"kept", "removed"}, {"kept", "added"}],
        ),
        patch(
            "apps.export.management.commands.migrate_graph._enum_values",
            side_effect=[
                {"Changed": {"old"}, "Gone": {"x"}},
                {"Changed": {"new"}},
            ],
        ),
    ):
        call_command(
            "migrate_graph", graph.pk, "--to-version", new.version, stdout=output
        )
    report = output.getvalue()
    assert "Added slots (1)" in report
    assert "Removed slots (1)" in report
    assert "Affected nodes (1)" in report
    assert "Affected edges (1)" in report
    assert "Action required" in report

    output = StringIO()
    with (
        patch(
            "apps.export.management.commands.migrate_graph._slot_names",
            side_effect=[{"kept"}, {"kept"}],
        ),
        patch(
            "apps.export.management.commands.migrate_graph._enum_values",
            side_effect=[{"Same": {"x"}}, {"Same": {"x"}}],
        ),
    ):
        call_command(
            "migrate_graph", graph.pk, "--to-version", new.version, stdout=output
        )
    assert "safe to migrate" in output.getvalue()


def test_migrate_graph_command_handles_lookup_and_same_version(graph):
    with pytest.raises(CommandError, match="Graph .* not found"):
        call_command("migrate_graph", 999999, "--to-version", "old")
    with pytest.raises(CommandError, match="not found in the database"):
        call_command("migrate_graph", graph.pk, "--to-version", "missing")

    output = StringIO()
    call_command("migrate_graph", graph.pk, "--to-version", "old", stdout=output)
    assert "already on this schema" in output.getvalue()


def test_load_ontology_command_selection_success_and_failure(db):
    output = StringIO()
    with (
        patch(
            "apps.ontology.management.commands.load_ontology.list_ontology_names",
            return_value=["envo", "pato"],
        ),
        patch(
            "apps.ontology.management.commands.load_ontology.preload_names",
            return_value=["envo"],
        ),
    ):
        call_command("load_ontology", stdout=output)
    assert "Available ontologies" in output.getvalue()

    output = StringIO()
    errors = StringIO()

    def fake_load(name, **kwargs):
        if name == "bad":
            raise ValueError("download failed")
        return kwargs["snapshot"], 12

    with patch(
        "apps.ontology.management.commands.load_ontology.load_ontology",
        side_effect=fake_load,
    ):
        call_command(
            "load_ontology",
            "envo",
            "bad",
            "--new-snapshot",
            stdout=output,
            stderr=errors,
        )
    assert "12 terms" in output.getvalue()
    assert "FAILED" in errors.getvalue()

    with pytest.raises(CommandError, match="single ontology"):
        call_command("load_ontology", "envo", "pato", "--source", "file.obo")


def test_process_loads_and_trigram_commands(db):
    # No pending requests exercises the one-shot worker's clean exit.
    call_command("process_ontology_loads")

    from apps.ontology.management.commands.create_trgm_index import Command

    command = Command()
    cursor = StringIO()
    command.stdout = cursor
    fake_cursor = patch("django.db.connection.cursor")
    with fake_cursor as cursor_factory:
        cursor_factory.return_value.__enter__.return_value = sql = (
            cursor_factory.return_value
        )
        command.handle()
    assert sql.execute.call_count == 3
    assert "indexes created" in cursor.getvalue()


def test_llm_noop_contract_and_dataclass_defaults():
    from apps.llm.proposer import NoOpProposer, ProposedEdge, ProposedNode

    node = ProposedNode("A")
    edge = ProposedEdge("A", "B")
    assert node.data == {}
    assert edge.data == {}
    assert NoOpProposer().propose(object(), object()) == ([], [])
