"""Semver-aware discovery of the CAMO schema files in config/schema/.

Tests should default to `latest_schema` / `latest_schema_yaml` (see conftest.py)
so they track whatever CAMO looks like today. A handful of tests are
deliberately pinned to a specific historical version — those use
`frozen_schema_path(version)` and must explain, in a comment, why that
particular version's behaviour is being frozen (see conftest.py fixtures).
"""

from __future__ import annotations

import re
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "config" / "schema"
_VERSION_RE = re.compile(r"camo-(\d+)\.(\d+)\.(\d+)\.yaml$")


def _version_key(path: Path) -> tuple[int, int, int]:
    match = _VERSION_RE.search(path.name)
    if not match:
        raise ValueError(f"Cannot parse a semver from schema filename: {path.name}")
    return tuple(int(part) for part in match.groups())


def available_schemas() -> list[Path]:
    """All config/schema/camo-*.yaml files, sorted oldest to newest."""
    paths = sorted(SCHEMA_DIR.glob("camo-*.yaml"), key=_version_key)
    if not paths:
        raise FileNotFoundError(f"No camo-*.yaml schema files found in {SCHEMA_DIR}")
    return paths


def latest_schema_path() -> Path:
    return available_schemas()[-1]


def oldest_schema_path() -> Path:
    return available_schemas()[0]


def frozen_schema_path(version: str) -> Path:
    """A specific historical version, pinned deliberately for a regression test.

    Raises loudly if the file has been pruned — these files must not be
    deleted by the on-disk cleanup in check_schema_updates/update_schema,
    since tests still depend on them as known-good historical snapshots.
    """
    path = SCHEMA_DIR / f"camo-{version}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Frozen regression fixture camo-{version}.yaml is missing from "
            "config/schema/. This file is pinned intentionally by a test and "
            "must not be pruned."
        )
    return path
