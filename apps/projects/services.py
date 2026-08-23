"""Business logic for projects: RIS import, PDF attachment, assignment."""

import hashlib
import io
import re
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import rispy
from django.conf import settings
from django.core.files.base import File
from django.db import connections, transaction

from apps.annotation.models import Edge, Node
from apps.audit.models import AuditEvent

from .models import Assignment, Document, Project
from .upload_validation import (
    validate_bundle_upload,
    validate_pdf_upload,
    validate_ris_upload,
)

# ---------------------------------------------------------------------------
# RIS import
# ---------------------------------------------------------------------------


def _ris_title(rec: dict) -> str:
    return (rec.get("title") or rec.get("primary_title") or "").strip() or "Untitled"


def _ris_authors(rec: dict) -> list[str]:
    for key in ("authors", "first_authors", "secondary_authors"):
        val = rec.get(key)
        if val:
            return list(val)
    return []


def _ris_year(rec: dict) -> int | None:
    for key in ("year", "publication_year"):
        val = rec.get(key)
        if val:
            s = str(val).split("/")[0].split("-")[0].strip()
            if s.isdigit():
                return int(s)
    return None


def _ris_doi(rec: dict) -> str | None:
    doi = (rec.get("doi") or "").strip()
    return doi or None


def _ris_journal(rec: dict) -> str:
    for key in ("journal_name", "secondary_title", "alternate_title3", "periodical"):
        val = (rec.get(key) or "").strip()
        if val:
            return val
    return ""


def _find_duplicate(project: Project, doi: str | None, title: str) -> Document | None:
    if doi:
        doc = Document.objects.filter(project=project, doi=doi).first()
        if doc:
            return doc
    return Document.objects.filter(project=project, title__iexact=title).first()


def import_ris_file(
    project: Project, file_obj
) -> tuple[list[Document], list[Document]]:
    """Parse *file_obj* as RIS and create Documents. Returns (created, skipped)."""
    validate_ris_upload(file_obj)
    file_obj.seek(0)
    raw = file_obj.read()
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw

    try:
        records = list(rispy.load(io.StringIO(text)))
    except Exception as exc:
        raise ValueError(f"Could not parse RIS file: {exc}") from exc

    created: list[Document] = []
    skipped: list[Document] = []

    for rec in records:
        title = _ris_title(rec)
        doi = _ris_doi(rec)

        duplicate = _find_duplicate(project, doi, title)
        if duplicate:
            skipped.append(duplicate)
            continue

        abstract = (rec.get("abstract") or "").strip()

        doc = Document.objects.create(
            project=project,
            source=Document.SOURCE_RIS_IMPORT,
            title=title,
            authors=_ris_authors(rec),
            year=_ris_year(rec),
            doi=doi,
            journal=_ris_journal(rec),
            abstract=abstract,
            # Abstract-only records use the abstract as initial canonical text
            # so abstract-level annotation is possible before a PDF is attached.
            canonical_text=abstract if abstract else None,
            ris_raw=rec,
        )
        created.append(doc)

    return created, skipped


# ---------------------------------------------------------------------------
# ZIP bundle import
# ---------------------------------------------------------------------------


@dataclass
class BundleImportResult:
    created: list[Document] = field(default_factory=list)
    skipped: list[Document] = field(default_factory=list)
    attached: list[Document] = field(default_factory=list)
    already_had_pdf: list[Document] = field(default_factory=list)
    unmatched_pdfs: list[str] = field(default_factory=list)
    extraction_deferred: list[Document] = field(default_factory=list)
    markdown_ingested: list[Document] = field(default_factory=list)


def _normalized_match_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _attachment_names(rec: dict) -> list[str]:
    names: list[str] = []
    for key in ("file_attachments1", "file_attachments2"):
        values = rec.get(key) or []
        if isinstance(values, str):
            values = [values]
        for value in values:
            for part in str(value).split(";"):
                name = part.strip().replace("\\", "/").rsplit("/", 1)[-1]
                if name:
                    names.append(name)
    return names


def _document_for_ris_record(project: Project, rec: dict) -> Document | None:
    return _find_duplicate(project, _ris_doi(rec), _ris_title(rec))


def _pdf_match_indexes(
    project: Project,
    records: list[dict],
) -> tuple[dict[str, Document], list[tuple[str, Document]]]:
    exact: dict[str, Document] = {}
    doi_refs: list[tuple[str, Document]] = []

    for rec in records:
        doc = _document_for_ris_record(project, rec)
        if not doc:
            continue

        title_key = _normalized_match_key(_ris_title(rec))
        if title_key:
            exact[title_key] = doc

        doi_key = _normalized_match_key(_ris_doi(rec))
        if doi_key:
            doi_refs.append((doi_key, doc))

        for name in _attachment_names(rec):
            attachment_key = _normalized_match_key(Path(name).stem)
            if attachment_key:
                exact[attachment_key] = doc

    return exact, doi_refs


def _match_pdf_to_document(
    filename: str,
    exact: dict[str, Document],
    doi_refs: list[tuple[str, Document]],
) -> Document | None:
    stem_key = _normalized_match_key(Path(filename).stem)
    if not stem_key:
        return None

    if stem_key in exact:
        return exact[stem_key]

    doi_matches = [doc for doi_key, doc in doi_refs if doi_key in stem_key]
    if len({doc.pk for doc in doi_matches}) == 1:
        return doi_matches[0]
    return None


def import_zipped_ris_bundle(project: Project, file_obj) -> BundleImportResult:
    """Import one RIS file and matching article PDFs from a ZIP archive.

    Text extraction is deliberately deferred. Extracting every PDF in a large
    bundle can exceed the web worker timeout; annotation views extract one PDF
    on demand, and the ``extract_text`` command supports proactive batch work.
    """
    result = BundleImportResult()
    validate_bundle_upload(file_obj)
    file_obj.seek(0)

    try:
        archive = zipfile.ZipFile(file_obj)
    except zipfile.BadZipFile as exc:
        raise ValueError("Upload a valid .zip file.") from exc

    with archive:
        entries = [
            info
            for info in archive.infolist()
            if not info.is_dir() and not info.filename.startswith("__MACOSX/")
        ]
        if len(entries) > settings.MAX_BUNDLE_FILES:
            raise ValueError(
                f"The ZIP archive contains more than {settings.MAX_BUNDLE_FILES} files."
            )

        total_size = sum(info.file_size for info in entries)
        if total_size > settings.MAX_BUNDLE_UNCOMPRESSED_BYTES:
            limit_mb = settings.MAX_BUNDLE_UNCOMPRESSED_BYTES // (1024 * 1024)
            raise ValueError(
                f"The ZIP archive expands beyond the {limit_mb} MB safety limit."
            )

        for info in entries:
            if info.flag_bits & 0x1:
                raise ValueError("Encrypted ZIP entries are not supported.")
            if info.file_size and (
                info.file_size / max(1, info.compress_size)
                > settings.MAX_ZIP_COMPRESSION_RATIO
            ):
                raise ValueError(
                    f'The ZIP entry "{Path(info.filename).name}" has an unsafe '
                    "compression ratio."
                )
            if (
                info.filename.lower().endswith(".pdf")
                and info.file_size > settings.MAX_PDF_UPLOAD_BYTES
            ):
                raise ValueError(
                    f'The PDF "{Path(info.filename).name}" exceeds the upload limit.'
                )
            if (
                info.filename.lower().endswith(".ris")
                and info.file_size > settings.MAX_RIS_UPLOAD_BYTES
            ):
                raise ValueError("The RIS file in the ZIP exceeds the upload limit.")
        ris_entries = [
            info for info in entries if info.filename.lower().endswith(".ris")
        ]
        if not ris_entries:
            raise ValueError("The ZIP archive must contain one .ris file.")
        if len(ris_entries) > 1:
            raise ValueError("The ZIP archive must contain exactly one .ris file.")

        ris_bytes = archive.read(ris_entries[0])
        ris_text = ris_bytes.decode("utf-8", errors="replace")
        try:
            records = list(rispy.load(io.StringIO(ris_text)))
        except Exception as exc:
            raise ValueError(f"Could not parse RIS file: {exc}") from exc

        result.created, result.skipped = import_ris_file(project, io.StringIO(ris_text))
        exact, doi_refs = _pdf_match_indexes(project, records)

        # Index .md sidecars by normalised stem so they can be matched to PDFs.
        md_sidecars: dict[str, str] = {}
        for info in entries:
            if info.filename.lower().endswith(".md"):
                stem = _normalized_match_key(Path(info.filename).stem)
                if stem:
                    md_sidecars[stem] = archive.read(info).decode(
                        "utf-8", errors="replace"
                    )

        for info in entries:
            if not info.filename.lower().endswith(".pdf"):
                continue

            safe_name = Path(info.filename).name
            doc = _match_pdf_to_document(safe_name, exact, doi_refs)
            if not doc:
                result.unmatched_pdfs.append(safe_name)
                continue
            if doc.has_pdf:
                result.already_had_pdf.append(doc)
                continue

            attach_pdf_to_document(doc, io.BytesIO(archive.read(info)), safe_name)
            result.attached.append(doc)
            result.extraction_deferred.append(doc)

            stem = _normalized_match_key(Path(safe_name).stem)
            if stem in md_sidecars:
                doc.canonical_markdown = md_sidecars[stem]
                doc.save(update_fields=["canonical_markdown"])
                result.markdown_ingested.append(doc)

    return result


# ---------------------------------------------------------------------------
# PDF attachment
# ---------------------------------------------------------------------------


def attach_pdf_to_document(
    doc: Document, file_obj, filename: str = "document.pdf"
) -> Document:
    """Store *file_obj* as the Document's PDF; compute SHA-256. Returns the updated doc."""
    validate_pdf_upload(file_obj)
    file_obj.seek(0)
    sha256 = _hash_limited_upload(file_obj, settings.MAX_PDF_UPLOAD_BYTES, "PDF files")
    file_obj.seek(0)
    safe_name = Path(filename).name or "document.pdf"
    doc.pdf_file.save(safe_name, File(file_obj), save=False)
    doc.sha256 = sha256
    doc.save(update_fields=["pdf_file", "sha256"])
    return doc


def extract_pdf_text_for_document(doc: Document) -> bool:
    """Extract canonical text for a stored PDF attachment."""
    from apps.documents import services as document_services

    return document_services.extract_text_from_pdf(doc)


def _hash_limited_upload(file_obj, maximum: int, label: str) -> str:
    hasher = hashlib.sha256()
    total = 0
    if hasattr(file_obj, "chunks"):
        chunks = file_obj.chunks()
    else:
        chunks = iter(lambda: file_obj.read(1024 * 1024), b"")
    for chunk in chunks:
        total += len(chunk)
        if total > maximum:
            limit_mb = maximum // (1024 * 1024)
            raise ValueError(f"{label} may not exceed {limit_mb} MB.")
        hasher.update(chunk)
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


def assign_document(
    project: Project,
    document: Document,
    annotator,
    assigned_by,
) -> Assignment:
    """Create or replace an assignment for (document, annotator)."""
    assignment, _ = Assignment.objects.update_or_create(
        document=document,
        annotator=annotator,
        defaults={
            "project": project,
            "assigned_by": assigned_by,
            "status": Assignment.STATUS_ASSIGNED,
        },
    )
    llm_config = getattr(project, "llm_config", None)
    if llm_config and llm_config.is_enabled and llm_config.trigger == "on_assignment":
        _trigger_llm_proposals_in_background(document, project)
    return assignment


def _trigger_llm_proposals_in_background(document: Document, project: Project) -> None:
    """Fire-and-forget the LLM proposal trigger on a daemon thread.

    Django's per-thread DB connection is normally closed by the
    request_finished signal, which a thread spawned off a view never gets —
    without this, each background trigger leaks a connection.
    """
    from apps.llm.triggers import propose_for_document

    def _run():
        try:
            propose_for_document(document, project)
        finally:
            connections.close_all()

    threading.Thread(target=_run, daemon=True).start()


def delete_project(project: Project, actor) -> dict:
    """Delete a project transactionally and remove its stored PDFs after commit."""
    with transaction.atomic():
        project = Project.objects.select_for_update().get(pk=project.pk)
        files = [
            (document.pdf_file.storage, document.pdf_file.name)
            for document in project.documents.exclude(pdf_file="")
            if document.pdf_file
        ]
        summary = {
            "name": project.name,
            "documents": project.documents.count(),
            "members": project.memberships.count(),
            "assignments": project.assignments.count(),
            "graphs": sum(
                document.graphs.count() for document in project.documents.all()
            ),
            "schema_sha256": (
                project.active_schema.sha256 if project.active_schema else None
            ),
            "ontology_manifest": (
                project.ontology_snapshot.manifest_sha256
                if project.ontology_snapshot
                else None
            ),
        }
        AuditEvent.objects.create(
            actor=actor,
            action="project.delete",
            target_type="Project",
            target_id=str(project.pk),
            diff=summary,
        )
        # Edges protect endpoint nodes, so remove them before graph/node cascades.
        Edge.objects.filter(graph__document__project=project).delete()
        Node.objects.filter(graph__document__project=project).delete()
        project.delete()

        # Delete files immediately after project deletion
        for storage, name in files:
            if name:
                storage.delete(name)

    return summary
