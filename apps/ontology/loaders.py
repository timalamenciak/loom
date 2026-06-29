"""Ontology loading: OBO/OWL → OntologyTerm records via pronto."""

from __future__ import annotations

import datetime
import hashlib
import io
import urllib.request
from pathlib import Path

import yaml
from django.conf import settings

from .models import OntologyRelease, OntologySnapshot, OntologyTerm

_CONFIG_PATH = Path(settings.BASE_DIR) / "config" / "ontologies.yaml"


def _load_config() -> dict:
    with _CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}


def ontology_config(name: str) -> dict | None:
    """Return the ontologies.yaml entry for *name*, or None."""
    cfg = _load_config()
    for entry in cfg.get("ontologies", []):
        if entry["name"] == name:
            return entry
    return None


def ontology_entries() -> list[dict]:
    return list(_load_config().get("ontologies", []))


def list_ontology_names() -> list[str]:
    return [o["name"] for o in _load_config().get("ontologies", [])]


def preload_names() -> list[str]:
    return _load_config().get("preload", [])


def get_or_create_active_snapshot(display_name: str = "default") -> OntologySnapshot:
    """Return the active snapshot, creating a bare one if none exists."""
    snap = OntologySnapshot.get_active()
    if snap is None:
        snap = OntologySnapshot.objects.create(name=display_name, is_active=True)
    return snap


def load_ontology(
    name: str,
    source: str | None = None,
    snapshot: OntologySnapshot | None = None,
    stdout=None,
) -> tuple[OntologySnapshot, int]:
    """Parse an OBO/OWL file and add terms to *snapshot*.

    If *snapshot* is None, the active snapshot is used (creating one if needed).
    Returns (snapshot, term_count).
    """
    cfg = ontology_config(name)
    if cfg is None:
        raise ValueError(f"Ontology '{name}' not found in config/ontologies.yaml")

    prefix = cfg["prefix"]
    url = source or cfg.get("local_path") or cfg.get("url")
    if not url:
        raise ValueError(f"No source URL or local_path configured for '{name}'")

    if stdout:
        stdout.write(f"  Parsing {name} from {url} …")

    if snapshot is None:
        snapshot = get_or_create_active_snapshot()
    elif snapshot.releases.exists() or snapshot.source_versions:
        # A snapshot may already be pinned by projects/graphs. Build a successor
        # instead of changing its reproducible manifest in place.
        previous = snapshot
        snapshot = OntologySnapshot.objects.create(
            name=previous.name,
            source_versions=dict(previous.source_versions),
            is_active=previous.is_active,
        )
        snapshot.releases.set(previous.releases.all())
    release, term_count = load_ontology_release(name, source=source, stdout=stdout)
    snapshot.releases.add(release)

    # Record provenance in snapshot
    meta = snapshot.source_versions
    meta[prefix] = {
        "name": name,
        "url": url,
        "sha256": release.source_sha256,
        "term_count": term_count,
        "loaded_at": datetime.datetime.utcnow().isoformat(),
    }
    snapshot.source_versions = meta
    snapshot.save(update_fields=["source_versions"])
    snapshot.refresh_manifest()

    return snapshot, term_count


def _read_source(source: str) -> bytes:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=120) as response:
            return response.read()
    return Path(source).read_bytes()


def load_ontology_release(
    name: str,
    source: str | None = None,
    stdout=None,
) -> tuple[OntologyRelease, int]:
    """Load one configured ontology into an immutable, reusable release."""
    import pronto

    cfg = ontology_config(name)
    if cfg is None:
        raise ValueError(f"Ontology '{name}' not found in config/ontologies.yaml")
    prefix = cfg["prefix"]
    url = source or cfg.get("local_path") or cfg.get("url")
    if not url:
        raise ValueError(f"No source URL or local_path configured for '{name}'")
    if stdout:
        stdout.write(f"  Fetching {name} from {url} …")

    content = _read_source(str(url))
    digest = hashlib.sha256(content).hexdigest()
    existing = OntologyRelease.objects.filter(
        prefix=prefix,
        source_sha256=digest,
        status=OntologyRelease.STATUS_READY,
    ).first()
    if existing:
        return existing, existing.term_count

    release = OntologyRelease.objects.create(
        name=name,
        prefix=prefix,
        source_url=str(url),
        source_sha256=digest,
        status=OntologyRelease.STATUS_LOADING,
    )
    try:
        ont = pronto.Ontology(io.BytesIO(content))
        batch = []
        for term in ont.terms():
            curie = str(term.id)
            term_prefix = curie.split(":")[0] if ":" in curie else prefix
            if term_prefix != prefix:
                continue
            synonyms = [syn.description for syn in (term.synonyms or [])]
            batch.append(
                OntologyTerm(
                    release=release,
                    prefix=prefix,
                    curie=curie,
                    label=term.name or curie,
                    synonyms=synonyms,
                    synonym_labels=" ".join(synonyms),
                    definition=str(term.definition) if term.definition else "",
                    obsolete=bool(term.obsolete),
                )
            )
            if len(batch) >= 2000:
                OntologyTerm.objects.bulk_create(batch, ignore_conflicts=True)
                batch = []
        if batch:
            OntologyTerm.objects.bulk_create(batch, ignore_conflicts=True)
        count = release.terms.count()
        release.term_count = count
        release.status = OntologyRelease.STATUS_READY
        release.save(update_fields=["term_count", "status"])
        return release, count
    except Exception as exc:
        release.status = OntologyRelease.STATUS_FAILED
        release.error = str(exc)
        release.save(update_fields=["status", "error"])
        raise
