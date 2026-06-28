"""Ad hoc Wikidata term persistence for per-project OntologyRelease.

When an annotator selects a live Wikidata result (``WD:Q*`` CURIE) from the
autocomplete, this module get-or-creates a backing ``OntologyTerm`` row before
the graph save commits, so the CURIE is not left dangling.

Validation strategy
-------------------
The frontend round-trips ``_wd_label`` and ``_wd_def`` hints via hidden form
inputs.  The server ALWAYS calls ``wbgetentities`` for the QID to obtain the
authoritative label and description before writing to the DB, so a compromised
browser cannot inject an arbitrary label for a real QID.  If the network call
fails, the server falls back to the frontend hint; if neither is available, the
OntologyTerm row is skipped silently and the CURIE is still stored in the node's
JSONB payload — annotation work must never block on Wikidata being reachable.

OntologyRelease provenance
--------------------------
Each project gets one ``OntologyRelease`` with ``source_kind="wikidata_adhoc"``
and ``prefix="WD"``.  Unlike bulk releases (immutable once loaded),
``source_sha256`` on an adhoc release is recomputed from the sorted
``(curie, label)`` set every time a new term is added.  This is expected: the
hash is a rolling fingerprint of accumulated picks, not a content-address for a
fixed snapshot.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from urllib.error import URLError

from django.db import IntegrityError, transaction

from .models import OntologyRelease, OntologyTerm
from .wikidata_search import _TIMEOUT, _USER_AGENT, _WIKIDATA_API

# ── Public API ────────────────────────────────────────────────────────────────


def resolve_wd_curies_in_data(project, data: dict, post) -> None:
    """Scan *data* (a ``BindingResult.data`` dict) for ``WD:Q*`` CURIEs.

    For each one found, calls ``get_or_create_adhoc_wikidata_term`` with the
    hint label/definition read from *post* (a Django ``QueryDict``).  Nested
    dicts are traversed recursively; list items that are strings or dicts are
    handled too.  A no-op if *data* contains no WD: CURIEs.
    """
    _scan_dict(project, data, post, prefix="")


def get_or_create_adhoc_wikidata_term(
    project,
    curie: str,
    *,
    hint_label: str = "",
    hint_definition: str = "",
) -> OntologyTerm | None:
    """Get or create an ``OntologyTerm`` row for a ``WD:Q*`` CURIE.

    Steps:
    1. If the term already exists in the project's adhoc release, return it
       immediately — no network call.
    2. Otherwise, call ``wbgetentities`` for the authoritative label/description.
    3. Fall back to *hint_label* / *hint_definition* if the network call fails.
    4. Create the term (and the release if this is the first pick for the project).
    5. Recompute ``source_sha256`` on the release.

    Returns the ``OntologyTerm``, or ``None`` if neither the network nor the
    hint could supply a label (the node save still proceeds without a backing row).
    """
    if not curie.startswith("WD:Q"):
        return None
    qid = curie[len("WD:"):]

    # Fast path: term already exists — skip network call entirely.
    with transaction.atomic():
        release = _get_or_create_adhoc_release(project)
        existing = OntologyTerm.objects.filter(release=release, curie=curie).first()
        if existing:
            return existing

    # Authoritative label/def from Wikidata — done OUTSIDE the save transaction
    # so we do not hold a DB lock open during the network round-trip.
    auth_label, auth_definition = _wbgetentities(qid)

    label = auth_label or hint_label
    definition = auth_definition or hint_definition

    if not label:
        return None

    with transaction.atomic():
        release = _get_or_create_adhoc_release(project)
        try:
            term, created = OntologyTerm.objects.get_or_create(
                release=release,
                curie=curie,
                defaults={
                    "prefix": "WD",
                    "label": label,
                    "synonyms": [],
                    "synonym_labels": "",
                    "definition": definition,
                    "obsolete": False,
                },
            )
        except IntegrityError:
            # Concurrent insert race — re-fetch.
            term = OntologyTerm.objects.get(release=release, curie=curie)
            created = False

        if created:
            _update_release_hash(release)
        return term


# ── Internals ─────────────────────────────────────────────────────────────────


def _scan_dict(project, data: dict, post, prefix: str) -> None:
    for key, value in data.items():
        full_key = f"{prefix}{key}" if prefix else key
        if isinstance(value, str) and value.startswith("WD:Q"):
            hint_label = post.get(f"{full_key}_wd_label", "")
            hint_def = post.get(f"{full_key}_wd_def", "")
            get_or_create_adhoc_wikidata_term(
                project, value,
                hint_label=hint_label,
                hint_definition=hint_def,
            )
        elif isinstance(value, dict):
            _scan_dict(project, value, post, prefix=f"{full_key}__")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, str) and item.startswith("WD:Q"):
                    hint_label = post.get(f"{full_key}_wd_label", "")
                    hint_def = post.get(f"{full_key}_wd_def", "")
                    get_or_create_adhoc_wikidata_term(
                        project, item,
                        hint_label=hint_label,
                        hint_definition=hint_def,
                    )
                elif isinstance(item, dict):
                    _scan_dict(project, item, post, prefix=f"{full_key}__{i}__")


def _get_or_create_adhoc_release(project) -> OntologyRelease:
    """Return (finding or creating) the per-project adhoc WD release."""
    release, _ = OntologyRelease.objects.get_or_create(
        project=project,
        prefix="WD",
        source_kind=OntologyRelease.SOURCE_KIND_WIKIDATA_ADHOC,
        defaults={
            "name": f"Wikidata ad hoc picks — {project.name}",
            "source_url": "https://www.wikidata.org/",
            "source_sha256": hashlib.sha256(b"").hexdigest(),
            "status": OntologyRelease.STATUS_READY,
        },
    )
    return release


def _update_release_hash(release: OntologyRelease) -> None:
    """Recompute ``source_sha256`` and ``term_count`` from the current term set.

    Sorted by CURIE so the hash is deterministic regardless of insertion order.
    The hash changes with every new term addition — this is expected behaviour
    for an accumulating adhoc release (see module docstring).
    """
    rows = list(
        release.terms.order_by("curie").values_list("curie", "label")
    )
    manifest = "\n".join(f"{curie}\t{label}" for curie, label in rows)
    new_hash = hashlib.sha256(manifest.encode()).hexdigest()
    OntologyRelease.objects.filter(pk=release.pk).update(
        source_sha256=new_hash,
        term_count=len(rows),
    )


def _wbgetentities(qid: str) -> tuple[str, str]:
    """Return (label, description) for *qid* from wbgetentities, or ("", "").

    Uses the same User-Agent and timeout as ``wikidata_search`` so both modules
    present identically to Wikidata's rate-limiter.
    """
    params = urllib.parse.urlencode(
        {
            "action": "wbgetentities",
            "ids": qid,
            "props": "labels|descriptions",
            "languages": "en",
            "format": "json",
        }
    )
    req = urllib.request.Request(
        f"{_WIKIDATA_API}?{params}",
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except (URLError, OSError, ValueError):
        return "", ""

    entity = data.get("entities", {}).get(qid, {})
    if entity.get("missing"):
        return "", ""

    label = entity.get("labels", {}).get("en", {}).get("value", "")
    description = entity.get("descriptions", {}).get("en", {}).get("value", "")
    return label, description
