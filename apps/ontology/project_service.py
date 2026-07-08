from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent

from .loaders import list_ontology_names, load_ontology_release, ontology_entries
from .models import (
    OntologyLoadItem,
    OntologyLoadRequest,
    OntologyRelease,
    OntologySnapshot,
)


def _ready_release(name: str):
    return (
        OntologyRelease.objects.filter(name=name, status=OntologyRelease.STATUS_READY)
        .order_by("-loaded_at")
        .first()
    )


def compose_snapshot(names: list[str]) -> OntologySnapshot:
    releases = [_ready_release(name) for name in sorted(set(names))]
    if any(release is None for release in releases):
        missing = [
            name
            for name, release in zip(sorted(set(names)), releases)
            if release is None
        ]
        raise ValueError("Ontologies are not loaded: " + ", ".join(missing))

    manifest = "\n".join(
        f"{release.prefix}:{release.source_sha256}" for release in releases
    )
    digest = hashlib.sha256(manifest.encode()).hexdigest()
    existing = OntologySnapshot.objects.filter(manifest_sha256=digest).first()
    if existing:
        return existing

    source_versions = {
        release.prefix: {
            "name": release.name,
            "url": release.source_url,
            "sha256": release.source_sha256,
            "term_count": release.term_count,
            "loaded_at": release.loaded_at.isoformat(),
        }
        for release in releases
    }
    snapshot = OntologySnapshot.objects.create(
        name="project-" + ("-".join(sorted(set(names))) or "empty"),
        source_versions=source_versions,
        manifest_sha256=digest,
    )
    snapshot.releases.set(releases)
    return snapshot


def request_project_ontologies(project, actor, names: list[str]):
    valid = set(list_ontology_names())
    names = sorted(set(names))
    unknown = set(names) - valid
    if unknown:
        raise ValueError("Unknown ontologies: " + ", ".join(sorted(unknown)))

    superseded = project.ontology_load_requests.filter(
        status=OntologyLoadRequest.STATUS_PENDING
    )
    superseded_ids = list(superseded.values_list("pk", flat=True))
    superseded.update(
        status=OntologyLoadRequest.STATUS_FAILED, error="Superseded by newer settings"
    )
    OntologyLoadItem.objects.filter(
        request_id__in=superseded_ids,
        status=OntologyLoadItem.STATUS_PENDING,
    ).update(
        status=OntologyLoadItem.STATUS_FAILED, error="Superseded by newer settings"
    )
    request = OntologyLoadRequest.objects.create(
        project=project,
        requested_by=actor,
        ontology_names=names,
    )
    prefixes = {entry["name"]: entry["prefix"] for entry in ontology_entries()}
    OntologyLoadItem.objects.bulk_create(
        [
            OntologyLoadItem(
                request=request,
                name=name,
                prefix=prefixes.get(name, name),
            )
            for name in names
        ]
    )
    if all(_ready_release(name) for name in names):
        process_load_request(request, allow_download=False)
        request.refresh_from_db()
    return request


def sync_ready_project_ontology_snapshots(names: list[str] | None = None) -> int:
    """Refresh project snapshots now satisfiable from ready ontology releases.

    Manual cache loads (``manage.py load_ontology``) create reusable releases but
    do not go through Project Settings. Projects still need their current
    snapshot rebuilt from those releases before autocomplete can see the newly
    loaded prefixes. Graphs remain pinned until a human explicitly upgrades
    them from the annotation page.
    """

    from apps.projects.models import Project

    changed_names = set(names or [])
    updated = 0
    projects = Project.objects.exclude(ontology_names=[]).select_related("created_by")
    for project in projects:
        project_names = sorted(set(project.ontology_names or []))
        if not project_names:
            continue
        if changed_names and not changed_names.intersection(project_names):
            continue
        try:
            snapshot = compose_snapshot(project_names)
        except ValueError:
            continue
        if project.ontology_snapshot_id == snapshot.pk:
            continue
        old_snapshot_id = project.ontology_snapshot_id
        project.ontology_snapshot = snapshot
        project.save(update_fields=["ontology_snapshot", "updated_at"])
        AuditEvent.objects.create(
            actor=project.created_by,
            action="project.ontology_snapshot.sync",
            target_type="Project",
            target_id=str(project.pk),
            diff={
                "old_snapshot_id": old_snapshot_id,
                "new_snapshot_id": snapshot.pk,
                "ontology_names": project_names,
            },
        )
        updated += 1
    return updated


def refresh_projects_for_ready_ontologies(names: list[str]) -> tuple[int, int]:
    """Retry satisfied project load requests, then sync matching projects."""

    if not names:
        return 0, 0

    changed_names = set(names)
    retried = 0
    requests = OntologyLoadRequest.objects.filter(
        status__in=[
            OntologyLoadRequest.STATUS_PENDING,
            OntologyLoadRequest.STATUS_FAILED,
        ]
    ).select_related("project", "requested_by")
    for request in requests:
        request_names = set(request.ontology_names or [])
        if changed_names and not changed_names.intersection(request_names):
            continue
        if not request_names or any(
            _ready_release(name) is None for name in request_names
        ):
            continue
        before = request.status
        process_load_request(request, allow_download=False)
        request.refresh_from_db()
        if (
            before != request.status
            or request.status == OntologyLoadRequest.STATUS_COMPLETE
        ):
            retried += 1

    synced = sync_ready_project_ontology_snapshots(list(changed_names))
    return retried, synced


def process_load_request(request, *, allow_download: bool = True):
    with transaction.atomic():
        request = (
            OntologyLoadRequest.objects.select_for_update()
            .select_related("project", "requested_by")
            .get(pk=request.pk)
        )
        if request.status not in {
            OntologyLoadRequest.STATUS_PENDING,
            OntologyLoadRequest.STATUS_FAILED,
        }:
            return request
        request.status = OntologyLoadRequest.STATUS_RUNNING
        request.error = ""
        request.started_at = timezone.now()
        request.save(update_fields=["status", "error", "started_at"])

        prefixes = {entry["name"]: entry["prefix"] for entry in ontology_entries()}
        for name in request.ontology_names:
            OntologyLoadItem.objects.get_or_create(
                request=request,
                name=name,
                defaults={"prefix": prefixes.get(name, name)},
            )

    active_item = None
    try:
        for name in request.ontology_names:
            active_item = request.items.get(name=name)
            active_item.status = OntologyLoadItem.STATUS_RUNNING
            active_item.error = ""
            active_item.started_at = timezone.now()
            active_item.finished_at = None
            active_item.save(
                update_fields=["status", "error", "started_at", "finished_at"]
            )

            release = _ready_release(name)
            if not release:
                if not allow_download:
                    raise ValueError(f"Ontology '{name}' has not been loaded yet")
                release, _count = load_ontology_release(name)
            active_item.status = OntologyLoadItem.STATUS_COMPLETE
            active_item.term_count = release.term_count
            active_item.finished_at = timezone.now()
            active_item.save(update_fields=["status", "term_count", "finished_at"])
            active_item = None
        snapshot = compose_snapshot(request.ontology_names)
        with transaction.atomic():
            project = (
                type(request.project)
                .objects.select_for_update()
                .get(pk=request.project_id)
            )
            old_snapshot_id = project.ontology_snapshot_id
            project.ontology_snapshot = snapshot
            project.save(update_fields=["ontology_snapshot", "updated_at"])
            request.status = OntologyLoadRequest.STATUS_COMPLETE
            request.finished_at = timezone.now()
            request.save(update_fields=["status", "finished_at"])
            AuditEvent.objects.create(
                actor=request.requested_by,
                action="project.ontologies.loaded",
                target_type="Project",
                target_id=str(project.pk),
                diff={
                    "old_snapshot_id": old_snapshot_id,
                    "new_snapshot_id": snapshot.pk,
                    "ontology_names": request.ontology_names,
                },
            )
    except Exception as exc:
        finished_at = timezone.now()
        if active_item is not None:
            active_item.status = OntologyLoadItem.STATUS_FAILED
            active_item.error = str(exc)
            active_item.finished_at = finished_at
            active_item.save(update_fields=["status", "error", "finished_at"])
        request.items.filter(status=OntologyLoadItem.STATUS_PENDING).update(
            status=OntologyLoadItem.STATUS_FAILED,
            error="Not attempted because another ontology failed to load.",
            finished_at=finished_at,
        )
        request.status = OntologyLoadRequest.STATUS_FAILED
        request.error = str(exc)
        request.finished_at = finished_at
        request.save(update_fields=["status", "error", "finished_at"])
    return request


def project_ontology_status(project) -> list[dict]:
    """Return display-ready status rows for the project's selected ontologies."""

    entries = {entry["name"]: entry for entry in ontology_entries()}
    snapshot_releases = {}
    if project.ontology_snapshot_id:
        snapshot_releases = {
            release.name: release
            for release in project.ontology_snapshot.releases.all()
        }

    latest = project.ontology_load_requests.prefetch_related("items").first()
    latest_items = {item.name: item for item in latest.items.all()} if latest else {}
    rows = []
    for name in project.ontology_names or []:
        entry = entries.get(name, {"name": name, "prefix": name, "description": ""})
        release = snapshot_releases.get(name)
        item = latest_items.get(name)
        if item is not None and item.status in {
            item.STATUS_PENDING,
            item.STATUS_RUNNING,
        }:
            status = item.status
            term_count = release.term_count if release else item.term_count
            error = item.error
        elif release is not None:
            status = "complete"
            term_count = release.term_count
            error = (
                f"Latest reload failed: {item.error}"
                if item and item.status == item.STATUS_FAILED
                else ""
            )
        elif item is not None:
            status = item.status
            term_count = item.term_count
            error = item.error
        else:
            status = "pending"
            term_count = 0
            error = "Waiting for an ontology load request."
        rows.append(
            {
                "name": name,
                "prefix": entry.get("prefix", name),
                "description": entry.get("description", ""),
                "status": status,
                "term_count": term_count,
                "error": error,
            }
        )
    return rows
