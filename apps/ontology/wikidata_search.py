"""Wikidata live term search for the ontology autocomplete.

The lookup first asks wbsearchentities for candidate QIDs, then filters them
before returning WD: CURIEs. Generic taxon searches use wbgetentities claims to
avoid high-frequency WDQS/SPARQL calls; narrower roots still use SPARQL for
transitive hierarchy checks.

Results are cached in-process for 60 s per (query, root_qid) pair to absorb
repeated keystrokes without hammering the remote APIs.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from urllib.error import URLError

from loom import __version__

_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
# Wikidata rate-limits non-compliant User-Agent strings regardless of volume.
_USER_AGENT = (
    f"Loom/{__version__} "
    "(EcoWeaver causal-mosaic annotation workbench; "
    "mailto:tim.alamenciak@gmail.com)"
)
_TIMEOUT = 8  # seconds per network call
_CACHE_TTL = 60  # seconds

_cache: dict[tuple, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def search(
    query: str,
    root_qid: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Return up to *limit* Wikidata taxa matching *query*.

    Each result is ``{"curie": "WD:Q<n>", "label": str, "description": str}``.
    Returns [] on any network or parse failure.

    When *root_qid* is given, results are restricted to that ontology branch
    where Loom can check the relationship cheaply enough for typeahead.
    """
    cache_key = (query.lower(), root_qid, limit)
    with _cache_lock:
        if cache_key in _cache:
            ts, cached = _cache[cache_key]
            if time.monotonic() - ts < _CACHE_TTL:
                return cached

    results = _search_uncached(query, root_qid, limit)

    with _cache_lock:
        now = time.monotonic()
        stale = [k for k, (ts, _) in _cache.items() if now - ts >= _CACHE_TTL]
        for k in stale:
            del _cache[k]
        _cache[cache_key] = (now, results)

    return results


# Internals


def _search_uncached(
    query: str,
    root_qid: str | None,
    limit: int,
) -> list[dict]:
    # Over-fetch so filtering still yields enough results.
    overfetch = min(limit * 2, 20)
    candidates = _wbsearch(query, overfetch)
    if not candidates:
        return []

    qids = [c["qid"] for c in candidates]
    if root_qid in {None, "Q16521"}:
        valid = _claim_filter(qids, root_qid)
    else:
        valid = _sparql_filter(qids, root_qid)

    results: list[dict] = []
    for c in candidates:
        if c["qid"] in valid:
            results.append(
                {
                    "curie": f"WD:{c['qid']}",
                    "label": c["label"],
                    "description": c.get("description", ""),
                }
            )
        if len(results) >= limit:
            break

    return results


def _claim_filter(qids: list[str], root_qid: str | None) -> set[str]:
    """Filter candidates using wbgetentities claims.

    Generic taxon lookup is on the high-frequency typing path.  Use the
    standard Wikidata API instead of WDQS/SPARQL so ordinary searches like
    "Canis" do not get blanked out by SPARQL rate limiting.
    """
    if not qids:
        return set()
    params = urllib.parse.urlencode(
        {
            "action": "wbgetentities",
            "ids": "|".join(qids),
            "props": "claims",
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
        return set()

    valid: set[str] = set()
    for qid, entity in (data.get("entities") or {}).items():
        claims = entity.get("claims") or {}
        if _has_claim(claims, "P105"):
            valid.add(qid)
            continue
        if root_qid == "Q16521" and _has_claim(claims, "P31", root_qid):
            valid.add(qid)
    return valid


def _has_claim(claims: dict, prop: str, target_qid: str | None = None) -> bool:
    for claim in claims.get(prop, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if target_qid is None and value:
            return True
        if isinstance(value, dict) and value.get("id") == target_qid:
            return True
    return False


def _wbsearch(query: str, limit: int) -> list[dict]:
    """Call wbsearchentities and return a list of {qid, label, description}."""
    params = urllib.parse.urlencode(
        {
            "action": "wbsearchentities",
            "search": query,
            "language": "en",
            "type": "item",
            "limit": limit,
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
        return []

    out: list[dict] = []
    for item in data.get("search", []):
        qid = item.get("id", "")
        if not qid.startswith("Q"):
            continue
        out.append(
            {
                "qid": qid,
                "label": item.get("label", qid),
                "description": item.get("description", ""),
            }
        )
    return out


def _sparql_filter(qids: list[str], root_qid: str | None) -> set[str]:
    """Return the subset of *qids* that are taxa (and descendants of *root_qid*)."""
    if not qids:
        return set()

    values = " ".join(f"wd:{q}" for q in qids)

    if root_qid:
        # UNION handles two cases:
        # 1. P171+ — descendants of a specific taxon node (e.g. Animalia Q23038)
        # 2. P31/P279* — instances/subclasses of a concept class (e.g. taxon Q16521)
        where = (
            f"VALUES ?item {{ {values} }}\n"
            f"    ?item wdt:P105 ?rank .\n"
            f"    {{ ?item wdt:P171+ wd:{root_qid} }}\n"
            f"    UNION\n"
            f"    {{ ?item wdt:P31/wdt:P279* wd:{root_qid} }}"
        )
    else:
        where = f"VALUES ?item {{ {values} }}\n" f"    ?item wdt:P105 ?rank ."

    sparql = f"SELECT ?item WHERE {{\n    {where}\n}}"
    params = urllib.parse.urlencode({"query": sparql, "format": "json"})
    req = urllib.request.Request(
        f"{_SPARQL_ENDPOINT}?{params}",
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/sparql-results+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except (URLError, OSError, ValueError):
        return set()

    valid: set[str] = set()
    for binding in data.get("results", {}).get("bindings", []):
        uri = binding.get("item", {}).get("value", "")
        # uri shape: "http://www.wikidata.org/entity/Q12345"
        if "/entity/Q" in uri:
            valid.add(uri.rsplit("/", 1)[-1])
    return valid
