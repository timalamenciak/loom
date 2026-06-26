"""Phase 1 tests: projects, RIS import, PDF attach, assignments, queue."""

import io
import zipfile

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.projects.models import Assignment, Document, Project, ProjectMembership
from apps.projects.services import (
    assign_document,
    attach_pdf_to_document,
    import_ris_file,
    import_zipped_ris_bundle,
)

User = get_user_model()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RIS = """\
TY  - JOUR
TI  - Buckthorn invasion reduces native plant diversity
AU  - Smith, Jane
AU  - Doe, John
PY  - 2021
DO  - 10.1234/test.2021
AB  - Common buckthorn (Rhamnus cathartica) is an invasive shrub.
JO  - Ecology Letters
ER  -

TY  - JOUR
TI  - Grassland restoration after shrub removal
AU  - Jones, Alice
PY  - 2022
AB  - Removing shrubs increases native grass cover.
ER  -
"""


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser("admin", "admin@test.example", "password")


@pytest.fixture
def annotator(db):
    return User.objects.create_user("annotator1", "ann@test.example", "password")


@pytest.fixture
def project(db, admin_user):
    p = Project.objects.create(name="Test Project", created_by=admin_user)
    ProjectMembership.objects.create(
        project=p, user=admin_user, role=ProjectMembership.ROLE_ADMIN
    )
    return p


@pytest.fixture
def project_with_annotator(project, annotator):
    ProjectMembership.objects.create(
        project=project, user=annotator, role=ProjectMembership.ROLE_ANNOTATOR
    )
    return project


# ---------------------------------------------------------------------------
# Model smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_project_str(project):
    assert str(project) == "Test Project"


@pytest.mark.django_db
def test_document_text_source_none():
    doc = Document(title="X", source=Document.SOURCE_MANUAL)
    assert doc.text_source == "none"
    assert not doc.is_annotatable


@pytest.mark.django_db
def test_document_text_source_abstract(project):
    doc = Document.objects.create(
        project=project,
        source=Document.SOURCE_RIS_IMPORT,
        title="Test",
        abstract="An abstract.",
        canonical_text="An abstract.",
    )
    assert doc.text_source == "abstract"
    assert doc.is_annotatable


# ---------------------------------------------------------------------------
# RIS import
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_import_ris_creates_documents(project):
    created, skipped = import_ris_file(project, io.BytesIO(SAMPLE_RIS.encode()))
    assert len(created) == 2
    assert len(skipped) == 0


@pytest.mark.django_db
def test_import_ris_sets_fields(project):
    created, _ = import_ris_file(project, io.BytesIO(SAMPLE_RIS.encode()))
    doc = next(d for d in created if d.doi)
    assert doc.doi == "10.1234/test.2021"
    assert "Smith" in doc.authors[0]
    assert doc.year == 2021
    assert "buckthorn" in doc.canonical_text.lower()


@pytest.mark.django_db
def test_import_ris_deduplication(project):
    import_ris_file(project, io.BytesIO(SAMPLE_RIS.encode()))
    created2, skipped2 = import_ris_file(project, io.BytesIO(SAMPLE_RIS.encode()))
    assert len(created2) == 0
    assert len(skipped2) == 2


@pytest.mark.django_db
def test_import_ris_50_records(project):
    """Acceptance criterion: import a 50-record RIS file."""
    records = ""
    for i in range(50):
        records += f"TY  - JOUR\nTI  - Paper number {i}\nAU  - Author {i}\nPY  - 2020\nER  -\n\n"
    created, skipped = import_ris_file(project, io.BytesIO(records.encode()))
    assert len(created) == 50
    assert len(skipped) == 0
    assert project.documents.count() == 50


def _zip_upload(files: dict[str, bytes], name: str = "bundle.zip") -> io.BytesIO:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)
    archive.seek(0)
    archive.name = name
    return archive


@pytest.mark.django_db
def test_import_zipped_ris_bundle_attaches_pdfs_by_title(project, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    upload = _zip_upload(
        {
            "refs.ris": SAMPLE_RIS.encode(),
            "Buckthorn invasion reduces native plant diversity.pdf": b"%PDF-1.4 buckthorn",
            "Grassland restoration after shrub removal.pdf": b"%PDF-1.4 grassland",
        }
    )

    result = import_zipped_ris_bundle(project, upload)

    assert len(result.created) == 2
    assert len(result.attached) == 2
    assert result.unmatched_pdfs == []
    assert all(doc.has_pdf for doc in project.documents.all())


@pytest.mark.django_db
def test_import_zipped_ris_bundle_attaches_pdfs_by_doi(project, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    upload = _zip_upload(
        {
            "refs.ris": SAMPLE_RIS.encode(),
            "10.1234_test.2021.pdf": b"%PDF-1.4 doi",
        }
    )

    result = import_zipped_ris_bundle(project, upload)

    doc = Document.objects.get(doi="10.1234/test.2021")
    assert result.attached == [doc]
    assert doc.has_pdf
    assert result.unmatched_pdfs == []


@pytest.mark.django_db
def test_import_zipped_ris_bundle_skips_existing_pdf(project, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    created, _ = import_ris_file(project, io.BytesIO(SAMPLE_RIS.encode()))
    doc = next(d for d in created if d.doi)
    attach_pdf_to_document(doc, io.BytesIO(b"%PDF-1.4 existing"), "existing.pdf")

    upload = _zip_upload(
        {
            "refs.ris": SAMPLE_RIS.encode(),
            "10.1234_test.2021.pdf": b"%PDF-1.4 replacement",
        }
    )

    result = import_zipped_ris_bundle(project, upload)

    assert len(result.created) == 0
    assert len(result.skipped) == 2
    assert result.attached == []
    assert result.already_had_pdf == [doc]


@pytest.mark.django_db
def test_import_zipped_ris_bundle_requires_one_ris(project):
    upload = _zip_upload({"paper.pdf": b"%PDF-1.4"})

    with pytest.raises(ValueError, match="one .ris"):
        import_zipped_ris_bundle(project, upload)


# ---------------------------------------------------------------------------
# PDF attach
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attach_pdf(project, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    doc = Document.objects.create(
        project=project, source=Document.SOURCE_RIS_IMPORT, title="Paper"
    )
    assert not doc.has_pdf
    pdf_bytes = b"%PDF-1.4 fake pdf content"
    attach_pdf_to_document(doc, io.BytesIO(pdf_bytes), "paper.pdf")
    doc.refresh_from_db()
    assert doc.has_pdf
    assert doc.sha256 is not None
    assert len(doc.sha256) == 64


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_assign_document(project_with_annotator, annotator, admin_user):
    doc = Document.objects.create(
        project=project_with_annotator,
        source=Document.SOURCE_RIS_IMPORT,
        title="Paper",
    )
    a = assign_document(project_with_annotator, doc, annotator, admin_user)
    assert a.status == Assignment.STATUS_ASSIGNED
    assert a.annotator == annotator


@pytest.mark.django_db
def test_assign_idempotent(project_with_annotator, annotator, admin_user):
    doc = Document.objects.create(
        project=project_with_annotator,
        source=Document.SOURCE_RIS_IMPORT,
        title="Paper",
    )
    a1 = assign_document(project_with_annotator, doc, annotator, admin_user)
    a2 = assign_document(project_with_annotator, doc, annotator, admin_user)
    assert a1.pk == a2.pk
    assert Assignment.objects.filter(document=doc).count() == 1


@pytest.mark.django_db
def test_annotator_queue_shows_only_assigned(client, project_with_annotator, annotator, admin_user):
    """Annotator sees exactly their assigned documents, nothing more."""
    import_ris_file(project_with_annotator, io.BytesIO(SAMPLE_RIS.encode()))
    docs = list(project_with_annotator.documents.all())
    # Assign only the first document
    assign_document(project_with_annotator, docs[0], annotator, admin_user)

    client.force_login(annotator)
    response = client.get(reverse("my-queue"))
    assert response.status_code == 200
    assignments = response.context["assignments"]
    assert len(assignments) == 1
    assert assignments[0].document == docs[0]


# ---------------------------------------------------------------------------
# Views — access control
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_non_member_cannot_see_project(client, project):
    stranger = User.objects.create_user("stranger", password="pass")
    client.force_login(stranger)
    response = client.get(reverse("project-detail", args=[project.pk]))
    assert response.status_code == 403


@pytest.mark.django_db
def test_annotator_cannot_import_ris(client, project_with_annotator, annotator):
    client.force_login(annotator)
    response = client.get(reverse("project-import-ris", args=[project_with_annotator.pk]))
    assert response.status_code == 403


@pytest.mark.django_db
def test_annotator_cannot_import_ris_bundle(client, project_with_annotator, annotator):
    client.force_login(annotator)
    response = client.get(
        reverse("project-import-ris-bundle", args=[project_with_annotator.pk])
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_sees_project_dashboard(client, project, admin_user):
    client.force_login(admin_user)
    response = client.get(reverse("project-detail", args=[project.pk]))
    assert response.status_code == 200
    assert response.context["is_admin"] is True


@pytest.mark.django_db
def test_project_list_view(client, project, admin_user):
    client.force_login(admin_user)
    response = client.get(reverse("project-list"))
    assert response.status_code == 200
    assert project in response.context["projects"]


@pytest.mark.django_db
def test_create_project_view(client, admin_user):
    client.force_login(admin_user)
    response = client.post(
        reverse("project-create"), {"name": "New Project", "description": ""}
    )
    assert response.status_code == 302
    assert Project.objects.filter(name="New Project").exists()


@pytest.mark.django_db
def test_ris_import_view(client, project, admin_user):
    client.force_login(admin_user)
    f = io.BytesIO(SAMPLE_RIS.encode())
    f.name = "refs.ris"
    response = client.post(
        reverse("project-import-ris", args=[project.pk]),
        {"ris_file": f},
        format="multipart",
    )
    assert response.status_code == 302
    assert project.documents.count() == 2


@pytest.mark.django_db
def test_ris_bundle_import_view(client, project, admin_user, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(admin_user)
    upload = _zip_upload(
        {
            "refs.ris": SAMPLE_RIS.encode(),
            "Buckthorn invasion reduces native plant diversity.pdf": b"%PDF-1.4 buckthorn",
        }
    )
    response = client.post(
        reverse("project-import-ris-bundle", args=[project.pk]),
        {"bundle_file": upload},
        format="multipart",
    )
    assert response.status_code == 302
    assert project.documents.count() == 2
    assert Document.objects.get(doi="10.1234/test.2021").has_pdf
