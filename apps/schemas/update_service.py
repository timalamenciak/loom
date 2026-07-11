"""Background update-check service.

Wraps the schema and ontology update checks that already exist as one-shot
management commands (`check_schema_updates`, `check_ontology_updates`) into a
single function that persists results to `UpdateCheckRecord` instead of just
printing them. This is what a scheduled task and the admin notification
banner both call — the management commands remain for interactive/CLI use.

Every phase fails soft, per the same network-restricted-deployment posture
as `apps/schemas/upstream.py`: a network error is logged and the check is
skipped, it never raises past `check_all_updates()`.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings

from apps.export.management.commands.migrate_graph import _enum_values, _slot_names
from apps.ontology.models import OntologyRelease
from apps.schemas.models import SchemaVersion, UpdateCheckRecord
from apps.schemas.schema_engine import invalidate_cache
from apps.schemas.services import load_schema_path
from apps.schemas.upstream import (
    UpstreamCheckError,
    download_asset,
    get_latest_release,
    version_tuple,
)

logger = logging.getLogger(__name__)

_ONTOLOGY_HEAD_TIMEOUT = 5
_SCHEMA_DOWNLOAD_TIMEOUT = 30
_USER_AGENT = "loom-update-checker"


def check_schema_update() -> UpdateCheckRecord | None:
    """Check causalmosaic's latest GitHub release against Loom's active schema.

    Returns the upserted record, or None if there's no active schema or the
    upstream check couldn't be completed — both are "nothing to report", not
    an error the caller needs to handle.
    """
    active = SchemaVersion.get_active()
    if active is None:
        logger.warning("check_schema_update: no active SchemaVersion, skipping")
        return None

    try:
        release = get_latest_release()
    except UpstreamCheckError as exc:
        logger.warning("check_schema_update: could not reach GitHub: %s", exc)
        return None

    is_available = version_tuple(release.version) > version_tuple(active.version)
    asset = release.schema_asset()
    download_url = asset.download_url if asset is not None else None

    diff_summary = {}
    if is_available and asset is not None:
        try:
            new_content = download_asset(asset)
        except UpstreamCheckError as exc:
            logger.warning(
                "check_schema_update: could not download %s: %s", asset.name, exc
            )
        else:
            new_stub = SimpleNamespace(linkml_yaml=new_content)
            old_slots = _slot_names(active)
            new_slots = _slot_names(new_stub)
            old_enums = _enum_values(active)
            new_enums = _enum_values(new_stub)
            diff_summary = {
                "added_slots": sorted(new_slots - old_slots),
                "removed_slots": sorted(old_slots - new_slots),
                "changed_enums": sorted(
                    name
                    for name in old_enums
                    if name in new_enums and old_enums[name] != new_enums[name]
                ),
            }

    record, _ = UpdateCheckRecord.objects.update_or_create(
        module_type=UpdateCheckRecord.MODULE_SCHEMA,
        module_name="camo",
        defaults={
            "current_version": active.version,
            "available_version": release.version if is_available else "",
            "is_update_available": is_available,
            "release_notes": release.body,
            "diff_summary": diff_summary,
            "download_url": download_url,
        },
    )
    return record


def check_ontology_updates() -> list[UpdateCheckRecord]:
    """HEAD-check every ready OntologyRelease with an upstream_url, persisting
    an UpdateCheckRecord per ontology. Unreachable releases are logged and
    skipped rather than recorded with stale data.
    """
    records = []
    releases = OntologyRelease.objects.filter(
        upstream_url__isnull=False, status=OntologyRelease.STATUS_READY
    )
    for release in releases:
        request = urllib.request.Request(
            release.upstream_url,
            method="HEAD",
            headers={"User-Agent": _USER_AGENT},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=_ONTOLOGY_HEAD_TIMEOUT
            ) as response:
                headers = response.headers
        except urllib.error.URLError as exc:
            logger.warning(
                "check_ontology_updates: could not reach %s (%s): %s",
                release.name,
                release.upstream_url,
                exc,
            )
            continue

        current = headers.get("ETag") or headers.get("Last-Modified") or ""
        is_available = bool(current) and current != release.source_etag

        record, _ = UpdateCheckRecord.objects.update_or_create(
            module_type=UpdateCheckRecord.MODULE_ONTOLOGY,
            module_name=release.name,
            defaults={
                "current_version": release.source_etag,
                "available_version": current if is_available else "",
                "is_update_available": is_available,
                "release_notes": "",
                "diff_summary": {"etag_changed": True} if is_available else {},
                "download_url": release.upstream_url,
            },
        )
        records.append(record)
    return records


def check_all_updates() -> dict:
    """Run schema + ontology update checks and persist UpdateCheckRecord rows.

    Never raises: each phase is additionally wrapped here so a bug in one
    phase can't stop the other from running under a scheduled task.
    """
    schema_record = None
    try:
        schema_record = check_schema_update()
    except Exception:
        logger.exception("check_all_updates: schema check failed unexpectedly")

    ontology_records: list[UpdateCheckRecord] = []
    try:
        ontology_records = check_ontology_updates()
    except Exception:
        logger.exception("check_all_updates: ontology check failed unexpectedly")

    return {"schema": schema_record, "ontology": ontology_records}


def apply_schema_update(
    record: UpdateCheckRecord, *, activate: bool = True
) -> tuple[SchemaVersion, bool]:
    """Download and load the schema release *record* points at.

    Fetches record.download_url directly (this is why check_schema_update()
    stores it) rather than re-resolving the release through the GitHub API —
    one less network round trip, and it keeps this function working even if
    a release later disappears/is retagged upstream.

    Guards against double-submit two ways: if record.available_version is
    already a loaded SchemaVersion (e.g. two concurrent confirm submits, or a
    previous apply succeeded but the record update raced), the existing row
    is reused instead of re-downloading. And if this record was already
    resolved by an earlier, separate apply (available_version has since been
    cleared — e.g. a browser back-button resubmit *after* success), it's
    resolved again from record.current_version instead of attempting a fresh
    download with an empty version string. Returns (schema, created) so
    callers can tell "just applied" from "already had this one" apart for
    the success message.

    Only marks the record resolved (is_update_available=False) once the
    schema is actually active — if the caller passes activate=False, the
    schema is loaded but the live app is still running the old one, so the
    banner must keep showing until someone actually activates it.

    Raises UpstreamCheckError on download or validation failure; callers
    report that to the user rather than silently failing.
    """
    existing = (
        SchemaVersion.objects.filter(version=record.available_version).first()
        if record.available_version
        else None
    )

    if existing is not None:
        schema, created = existing, False
    elif not record.is_update_available and record.current_version:
        schema = SchemaVersion.objects.filter(version=record.current_version).first()
        if schema is None:
            raise UpstreamCheckError(
                f"No SchemaVersion found for {record.current_version!r}; "
                "this update record may be stale."
            )
        created = False
    else:
        if not record.download_url:
            raise UpstreamCheckError("No download URL recorded for this update.")

        request = urllib.request.Request(
            record.download_url, headers={"User-Agent": _USER_AGENT}
        )
        try:
            with urllib.request.urlopen(
                request, timeout=_SCHEMA_DOWNLOAD_TIMEOUT
            ) as response:
                content = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise UpstreamCheckError(
                f"Could not download {record.download_url}: {exc}"
            ) from exc

        target_path = (
            Path(settings.BASE_DIR)
            / "config"
            / "schema"
            / f"camo-{record.available_version}.yaml"
        )
        target_path.write_text(content, encoding="utf-8")
        try:
            schema, created = load_schema_path(
                target_path, version=record.available_version, activate=False
            )
        except ValueError as exc:
            raise UpstreamCheckError(
                f"Downloaded schema failed validation: {exc}"
            ) from exc

    if activate and not schema.is_active:
        schema.is_active = True
        schema.save(update_fields=["is_active"])
        invalidate_cache()

    if schema.is_active:
        UpdateCheckRecord.objects.filter(pk=record.pk).update(
            is_update_available=False,
            current_version=schema.version,
            available_version="",
            diff_summary={},
        )

    return schema, created


def apply_ontology_update(record: UpdateCheckRecord) -> None:
    """Best-effort reload of an ontology after an update is detected.

    Ontology files can be large, so this is meant to be run off the request
    thread (see apps.schemas.views.ApplyUpdateView) — it runs synchronously
    wherever it's called and never raises, logging failures instead, since
    nothing is waiting on its return value.

    load_ontology() creates a new, separate OntologyRelease row (releases are
    immutable/content-addressed) rather than updating the one this
    UpdateCheckRecord was checked against, and it never sets upstream_url/
    source_etag on that new row at all. Left alone, that means: (a) the row
    check_ontology_updates() was polling still has upstream_url set and gets
    checked forever even though it's superseded, and (b) the new row it
    should be polling instead has no upstream_url, so it's invisible to
    every future check — the update we just applied would look pending
    again on the next scheduled check. So once the reload succeeds, this
    moves upstream_url from the old release to the new one and sets its
    source_etag from record.available_version — the ETag check_ontology_updates()
    already discovered when it flagged this update, so no second HTTP round
    trip is needed here.
    """
    from apps.ontology.loaders import load_ontology as load_ontology_terms

    old_release = (
        OntologyRelease.objects.filter(
            name=record.module_name, upstream_url__isnull=False
        )
        .order_by("-loaded_at")
        .first()
    )

    try:
        load_ontology_terms(record.module_name)
    except Exception:
        logger.exception(
            "apply_ontology_update: reload failed for %s", record.module_name
        )
        return

    new_release = (
        OntologyRelease.objects.filter(name=record.module_name)
        .order_by("-loaded_at")
        .first()
    )
    if (
        new_release is not None
        and old_release is not None
        and new_release.pk != old_release.pk
    ):
        new_release.upstream_url = old_release.upstream_url
        new_release.source_etag = record.available_version or old_release.source_etag
        new_release.save(update_fields=["upstream_url", "source_etag"])
        old_release.upstream_url = None
        old_release.save(update_fields=["upstream_url"])

    UpdateCheckRecord.objects.filter(pk=record.pk).update(
        is_update_available=False, available_version="", diff_summary={}
    )
