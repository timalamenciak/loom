"""
python manage.py import_nodes_edges <graph_pk> file.xlsx|file.yaml [--full-sync] [--apply]

Thin CLI wrapper around the same build_import_plan()/apply_import_plan()
core the web import views use (apps/export/graph_import.py). A single
manage.py invocation is one process, so there's no preview/apply request
boundary to bridge here — no cache token needed; --apply builds and
immediately applies the plan in one call.

Default (no --apply) prints the dry-run report and writes nothing — the
same dry-run/apply split as migrate_graph.
"""

import hashlib

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.annotation.models import CausalGraph
from apps.export.graph_import import (
    ImportParseError,
    apply_import_plan,
    build_import_plan,
    render_plan_text,
)
from apps.export.import_excel import parse_xlsx_import
from apps.export.import_yaml import parse_yaml_import
from apps.schemas.schema_engine import get_schema_view


def _parse_file(path: str) -> tuple[list[dict], list[dict], str]:
    lower = path.lower()
    if lower.endswith(".xlsx"):
        with open(path, "rb") as f:
            node_rows, edge_rows = parse_xlsx_import(f)
        return node_rows, edge_rows, "xlsx"
    if lower.endswith((".yaml", ".yml")):
        with open(path, "rb") as f:
            node_rows, edge_rows = parse_yaml_import(f)
        return node_rows, edge_rows, "yaml"
    raise CommandError("Import files must be .xlsx, .yaml, or .yml.")


class Command(BaseCommand):
    help = "Bulk-import (and optionally override) nodes/edges on a graph from Excel or YAML."

    def add_arguments(self, parser):
        parser.add_argument("graph_pk", type=int, help="Primary key of the graph")
        parser.add_argument("import_file", help="Path to a .xlsx, .yaml, or .yml file")
        parser.add_argument(
            "--full-sync",
            action="store_true",
            help="Delete any node/edge on the graph not present in the file",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Commit the import (default: print a dry-run report only)",
        )
        parser.add_argument(
            "--actor",
            help="Username to attribute the import to (defaults to the graph's annotator)",
        )

    def handle(self, *args, **options):
        try:
            graph = CausalGraph.objects.select_related(
                "schema_version", "document__project", "annotator"
            ).get(pk=options["graph_pk"])
        except CausalGraph.DoesNotExist:
            raise CommandError(f"No graph with id {options['graph_pk']}.")

        try:
            with open(options["import_file"], "rb") as f:
                source_sha256 = hashlib.sha256(f.read()).hexdigest()
            node_rows, edge_rows, import_format = _parse_file(options["import_file"])
        except FileNotFoundError:
            raise CommandError(f"File not found: {options['import_file']}")
        except ImportParseError as exc:
            raise CommandError(str(exc))

        actor = graph.annotator
        if options.get("actor"):
            try:
                actor = User.objects.get(username=options["actor"])
            except User.DoesNotExist:
                raise CommandError(f"No user with username {options['actor']!r}.")

        schema_view = get_schema_view(graph.schema_version, graph.document.project)
        plan = build_import_plan(
            graph,
            node_rows,
            edge_rows,
            schema_view=schema_view,
            full_sync=options["full_sync"],
            source_sha256=source_sha256,
            format=import_format,
            uploaded_by_id=actor.pk,
        )

        self.stdout.write(render_plan_text(plan))

        if not options["apply"]:
            return

        counts = apply_import_plan(plan, actor)
        self.stdout.write(
            self.style.SUCCESS(
                f"Applied: {counts['nodes_create']} node(s) created, "
                f"{counts['nodes_update']} updated, {counts['edges_create']} edge(s) created, "
                f"{counts['edges_update']} updated."
            )
        )
