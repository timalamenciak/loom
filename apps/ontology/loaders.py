"""Ontology loading: OBO/OWL → OntologyTerm records via pronto."""

from __future__ import annotations

import contextlib
import hashlib
import io
import urllib.request
from pathlib import Path

import yaml
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import OntologyRelease, OntologySnapshot, OntologyTerm

_CONFIG_PATH = Path(settings.BASE_DIR) / "config" / "ontologies.yaml"


@contextlib.contextmanager
def _pronto_assume_utf8():
    """Make pronto decode OBO/OWL content as UTF-8 instead of guessing.

    OBO 1.4 mandates UTF-8. pronto otherwise runs chardet on a small peeked
    prefix and can misdetect a genuinely UTF-8 file as Windows-1252 from a
    low-confidence sample, then crash decoding a later multi-byte sequence
    (observed with ELMO's OBO release, which uses curly quotes in a
    definition — plain ASCII-only sources like ENVO's core file never hit
    this). Scoped to the parse call and restored immediately after.
    """
    import pronto.ontology
    import pronto.utils.io as pronto_io

    original = pronto_io.decompress

    def _decompress_utf8(reader, path=None, encoding=None):
        return original(reader, path=path, encoding=encoding or "utf-8")

    # `pronto.ontology` did `from .utils.io import decompress`, which binds
    # its own name in that module's namespace — patching pronto.utils.io
    # alone does not affect the reference pronto.ontology.Ontology() actually
    # calls, so both bindings need patching.
    pronto_io.decompress = _decompress_utf8
    pronto.ontology.decompress = _decompress_utf8
    try:
        yield
    finally:
        pronto_io.decompress = original
        pronto.ontology.decompress = original


def _load_config() -> dict:
    with _CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}


def _adhoc_entries() -> list[dict]:
    """Return AdHocOntologySource rows as entry dicts, silently skipping DB errors."""
    try:
        from .models import AdHocOntologySource

        return [
            {
                "name": src.name,
                "prefix": src.prefix,
                "url": src.url,
                "description": src.description,
            }
            for src in AdHocOntologySource.objects.all()
        ]
    except Exception:
        return []


def ontology_config(name: str) -> dict | None:
    """Return the entry for *name* from ontologies.yaml, then the DB, or None."""
    cfg = _load_config()
    for entry in cfg.get("ontologies", []):
        if entry["name"] == name:
            return entry
    for entry in _adhoc_entries():
        if entry["name"] == name:
            return entry
    return None


def ontology_entries() -> list[dict]:
    """Return all ontology entries: YAML first, then DB-only additions."""
    yaml_entries = list(_load_config().get("ontologies", []))
    yaml_keys = {e["name"].lower() for e in yaml_entries} | {
        e["prefix"].lower() for e in yaml_entries
    }
    merged = list(yaml_entries)
    for entry in _adhoc_entries():
        if (
            entry["name"].lower() not in yaml_keys
            and entry["prefix"].lower() not in yaml_keys
        ):
            merged.append(entry)
    return merged


def list_ontology_names() -> list[str]:
    return [o["name"] for o in ontology_entries()]


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
        "loaded_at": timezone.now().isoformat(),
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


def _descendant_closure(ont, root_terms: list[str]) -> set[str]:
    """Return the lowercased id set of *root_terms* plus all their OBO subclasses.

    Unknown root CURIEs (typo, or absent from this particular release) are
    skipped rather than raised — a config change to root_terms should never
    turn into a load failure for the whole ontology.
    """
    by_id = {str(term.id).lower(): term for term in ont.terms()}
    allowed: set[str] = set()
    for root in root_terms:
        term = by_id.get(root.lower())
        if term is None:
            continue
        for sub in term.subclasses(with_self=True):
            allowed.add(str(sub.id).lower())
    return allowed


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

    # Optional branch scoping: index only root_terms and their descendants
    # instead of every term with a matching prefix. Mirrors the same
    # seed-list/MIREOT pattern ELMO's own build uses against ENVO (see
    # src/ontology/imports/envo_terms.txt upstream) — a huge source ontology
    # doesn't need to be cached in full when only one branch is ever routed to.
    root_terms = sorted({str(r) for r in (cfg.get("root_terms") or [])})
    include_descendants = bool(cfg.get("include_descendants"))
    scope = root_terms if include_descendants else []

    existing = OntologyRelease.objects.filter(
        prefix=prefix,
        source_sha256=digest,
        scope_root_curies=scope,
        status=OntologyRelease.STATUS_READY,
    ).first()
    if existing:
        return existing, existing.term_count

    release = OntologyRelease.objects.create(
        name=name,
        prefix=prefix,
        source_url=str(url),
        source_sha256=digest,
        scope_root_curies=scope,
        status=OntologyRelease.STATUS_LOADING,
    )
    try:
        with transaction.atomic():
            with _pronto_assume_utf8():
                ont = pronto.Ontology(io.BytesIO(content))
            allowed_ids = _descendant_closure(ont, root_terms) if scope else None
            batch = []
            for term in ont.terms():
                curie = str(term.id)
                term_prefix = curie.split(":")[0] if ":" in curie else prefix
                # Case-insensitive: some sources (e.g. ELMO's own OBO release)
                # emit lowercase CURIEs (`elmo:3620020`) while Loom/CAMO use
                # the uppercase prefix (`ELMO:`) everywhere else. Without this,
                # every term from such a source is silently dropped.
                if term_prefix.lower() != prefix.lower():
                    continue
                if allowed_ids is not None and curie.lower() not in allowed_ids:
                    continue
                curie = f"{prefix}:{curie.split(':', 1)[1]}" if ":" in curie else curie
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
