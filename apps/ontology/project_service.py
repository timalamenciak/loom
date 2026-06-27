from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent

from .loaders import list_ontology_names, load_ontology_release
from .models import OntologyLoadRequest, OntologyRelease, OntologySnapshot


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

    project.ontology_load_requests.filter(
        status=OntologyLoadRequest.STATUS_PENDING
    ).update(
        status=OntologyLoadRequest.STATUS_FAILED, error="Superseded by newer settings"
    )
    request = OntologyLoadRequest.objects.create(
        project=project,
        requested_by=actor,
        ontology_names=names,
    )
    if all(_ready_release(name) for name in names):
        process_load_request(request, allow_download=False)
        request.refresh_from_db()
    return request


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

    try:
        for name in request.ontology_names:
            if not _ready_release(name):
                if not allow_download:
                    raise ValueError(f"Ontology '{name}' has not been loaded yet")
                load_ontology_release(name)
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
        request.status = OntologyLoadRequest.STATUS_FAILED
        request.error = str(exc)
        request.finished_at = timezone.now()
        request.save(update_fields=["status", "error", "finished_at"])
    return request
