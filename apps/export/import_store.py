"""Cache-token carry-over for the web upload -> preview -> apply import flow.

An ``ImportPlan`` is plain data (dicts/strings/ints, no live ORM instances),
so it's cheap and safe to pickle through whatever cache backend is
configured (LocMemCache in dev/test, django_redis in prod — already shared
across gunicorn workers today for the schema-update-check debounce, see
loom/settings/prod.py).

Deliberately not re-upload-and-trust: re-posting the file on Apply and
re-parsing would reopen the exact race the preview/apply split exists to
prevent (the file changing between preview and apply), and would need
either a hidden base64 blob round-tripped to the browser or a server-side
temp file — the same "stash state between requests" problem, worse.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.core.cache import cache

from .graph_import import ImportPlan

IMPORT_PLAN_CACHE_PREFIX = "graph-import-plan"


def _key(token: str) -> str:
    return f"{IMPORT_PLAN_CACHE_PREFIX}:{token}"


def stash_plan(plan: ImportPlan) -> str:
    token = secrets.token_urlsafe(24)
    cache.set(_key(token), plan, timeout=settings.LOOM_IMPORT_PLAN_TTL_SECONDS)
    return token


def load_plan(token: str) -> ImportPlan | None:
    if not token:
        return None
    return cache.get(_key(token))


def discard_plan(token: str) -> None:
    cache.delete(_key(token))
