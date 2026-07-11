#!/usr/bin/env python
"""Pre-upgrade / CI readiness check for a Loom database.

Run before upgrading a self-hosted instance (see docs/migration-v0-to-v1.md),
or as a CI gate against a freshly migrated database:

    python scripts/check_migration_readiness.py

Exits 0 if every check passes. Exits 1, with a descriptive message for each
failing check, otherwise. Uses whatever DJANGO_SETTINGS_MODULE is already set
in the environment — matching manage.py's own default of loom.settings.dev
when unset, so pointing this at a specific deployment just means setting the
same env vars you'd use for that deployment's manage.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "loom.settings.dev")

import django  # noqa: E402

django.setup()

from apps.annotation.models import CausalGraph, Edge, Node  # noqa: E402
from apps.export.validators import validate_graph  # noqa: E402
from apps.ontology.models import OntologySnapshot  # noqa: E402
from apps.schemas.models import SchemaVersion  # noqa: E402


def check_active_schema() -> list[str]:
    if SchemaVersion.objects.filter(is_active=True).exists():
        return []
    return [
        "No active SchemaVersion. Run: "
        "python manage.py load_schema <path> --activate"
    ]


def check_ontology_snapshot() -> list[str]:
    if OntologySnapshot.objects.exists():
        return []
    return ["No OntologySnapshot exists. Run: python manage.py load_ontology --all"]


def check_no_orphaned_schema_version() -> list[str]:
    errors = []
    orphaned_nodes = Node.objects.filter(graph__schema_version__isnull=True).count()
    if orphaned_nodes:
        errors.append(
            f"{orphaned_nodes} Node row(s) belong to a graph with no schema_version."
        )
    orphaned_edges = Edge.objects.filter(graph__schema_version__isnull=True).count()
    if orphaned_edges:
        errors.append(
            f"{orphaned_edges} Edge row(s) belong to a graph with no schema_version."
        )
    return errors


def check_graphs_export_cleanly() -> list[str]:
    graphs = CausalGraph.objects.select_related(
        "document", "schema_version", "ontology_snapshot"
    )
    total = graphs.count()
    failures: list[str] = []
    for graph in graphs:
        is_valid, messages = validate_graph(graph)
        if not is_valid:
            detail = "; ".join(messages) or "unknown validation error"
            failures.append(
                f"Graph {graph.pk} (document {graph.document_id}): {detail}"
            )
    if failures:
        return [f"{len(failures)} of {total} graph(s) failed export validation:"] + [
            f"  {line}" for line in failures
        ]
    return []


CHECKS: list[tuple[str, "callable[[], list[str]]"]] = [
    ("Active schema exists", check_active_schema),
    ("Ontology snapshot exists", check_ontology_snapshot),
    ("No node/edge with a missing schema_version", check_no_orphaned_schema_version),
    ("Every graph exports without validation errors", check_graphs_export_cleanly),
]


def main() -> int:
    all_errors: list[str] = []
    for name, check in CHECKS:
        errors = check()
        if errors:
            print(f"[FAIL] {name}")
            for line in errors:
                print(f"       {line}")
            all_errors.extend(errors)
        else:
            print(f"[ OK ] {name}")

    if all_errors:
        print(f"\n{len(all_errors)} issue(s) found — not ready to upgrade.")
        return 1

    print("\nAll checks passed — ready to upgrade.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
