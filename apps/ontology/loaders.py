"""Ontology loading: OBO/OWL → OntologyTerm records via pronto."""

from __future__ import annotations

import datetime
from pathlib import Path

import yaml

from .models import OntologySnapshot, OntologyTerm

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "ontologies.yaml"


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
    import pronto

    cfg = ontology_config(name)
    if cfg is None:
        raise ValueError(f"Ontology '{name}' not found in config/ontologies.yaml")

    prefix = cfg["prefix"]
    url = source or cfg.get("local_path") or cfg.get("url")
    if not url:
        raise ValueError(f"No source URL or local_path configured for '{name}'")

    if stdout:
        stdout.write(f"  Parsing {name} from {url} …")

    ont = pronto.Ontology(url)

    if snapshot is None:
        snapshot = get_or_create_active_snapshot()

    # Remove any existing terms for this prefix in the snapshot
    OntologyTerm.objects.filter(snapshot=snapshot, prefix=prefix).delete()

    batch: list[OntologyTerm] = []
    for term in ont.terms():
        curie = str(term.id)
        term_prefix = curie.split(":")[0] if ":" in curie else prefix
        if term_prefix != prefix:
            continue  # Skip cross-imported terms

        synonyms = [syn.description for syn in (term.synonyms or [])]
        definition = str(term.definition) if term.definition else ""

        batch.append(
            OntologyTerm(
                snapshot=snapshot,
                prefix=prefix,
                curie=curie,
                label=term.name or curie,
                synonyms=synonyms,
                synonym_labels=" ".join(synonyms),
                definition=definition,
                obsolete=bool(term.obsolete),
            )
        )

        if len(batch) >= 2000:
            OntologyTerm.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []

    if batch:
        OntologyTerm.objects.bulk_create(batch, ignore_conflicts=True)

    term_count = OntologyTerm.objects.filter(snapshot=snapshot, prefix=prefix).count()

    # Record provenance in snapshot
    meta = snapshot.source_versions
    meta[prefix] = {
        "name": name,
        "url": url,
        "term_count": term_count,
        "loaded_at": datetime.datetime.utcnow().isoformat(),
    }
    snapshot.source_versions = meta
    snapshot.save(update_fields=["source_versions"])

    return snapshot, term_count
