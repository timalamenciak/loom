"""Shared upload limits enforced at both form and service boundaries."""

from __future__ import annotations

from django.conf import settings


class UploadValidationError(ValueError):
    """Raised when an uploaded research artifact is unsafe to process."""


def _stream_size(file_obj) -> int | None:
    size = getattr(file_obj, "size", None)
    if size is not None:
        return int(size)
    try:
        position = file_obj.tell()
        file_obj.seek(0, 2)
        size = file_obj.tell()
        file_obj.seek(position)
        return size
    except (AttributeError, OSError):
        return None


def _validate_size(file_obj, maximum: int, label: str) -> None:
    size = _stream_size(file_obj)
    if size is not None and size > maximum:
        limit_mb = maximum // (1024 * 1024)
        raise UploadValidationError(f"{label} may not exceed {limit_mb} MB.")


def validate_pdf_upload(file_obj) -> None:
    """Validate size and the PDF file signature without trusting metadata."""
    _validate_size(file_obj, settings.MAX_PDF_UPLOAD_BYTES, "PDF files")
    try:
        position = file_obj.tell()
        file_obj.seek(0)
        header = file_obj.read(1024)
        file_obj.seek(position)
    except (AttributeError, OSError) as exc:
        raise UploadValidationError("The PDF upload could not be read.") from exc
    if b"%PDF-" not in header:
        raise UploadValidationError("The uploaded file is not a valid PDF.")


def validate_ris_upload(file_obj) -> None:
    _validate_size(file_obj, settings.MAX_RIS_UPLOAD_BYTES, "RIS files")


def validate_bundle_upload(file_obj) -> None:
    _validate_size(file_obj, settings.MAX_BUNDLE_UPLOAD_BYTES, "ZIP bundles")


def validate_graph_import_upload(file_obj, filename: str) -> None:
    """Validate size and container signature for a graph bulk-import upload.

    .xlsx files are zip containers (signature ``PK``); .yaml/.yml files have
    no fixed binary signature to check here — malformed YAML is caught by
    the parser at import time instead (apps.export.import_yaml).
    """
    _validate_size(file_obj, settings.MAX_GRAPH_IMPORT_UPLOAD_BYTES, "Import files")
    lower = (filename or "").lower()
    if lower.endswith(".xlsx"):
        try:
            position = file_obj.tell()
            file_obj.seek(0)
            header = file_obj.read(4)
            file_obj.seek(position)
        except (AttributeError, OSError) as exc:
            raise UploadValidationError("The Excel upload could not be read.") from exc
        if header[:2] != b"PK":
            raise UploadValidationError(
                "The uploaded file is not a valid .xlsx workbook."
            )
    elif not lower.endswith((".yaml", ".yml")):
        raise UploadValidationError("Import files must be .xlsx, .yaml, or .yml.")
