"""
python manage.py validate_graph <graph_pk>
python manage.py validate_graph --all
"""

from django.core.management.base import BaseCommand, CommandError

from apps.annotation.models import CausalGraph
from apps.export.validators import validate_graph


class Command(BaseCommand):
    help = "Validate a CausalGraph (or every graph) against its pinned LinkML schema"

    def add_arguments(self, parser):
        parser.add_argument(
            "graph_pk", type=int, nargs="?", help="Primary key of the graph"
        )
        parser.add_argument(
            "--all",
            action="store_true",
            default=False,
            help="Validate every CausalGraph instead of a single one — each "
            "graph is checked against the schema it's pinned to, not "
            "necessarily the currently active one.",
        )

    def handle(self, *args, **options):
        if options["all"]:
            if options["graph_pk"] is not None:
                raise CommandError("Pass either graph_pk or --all, not both.")
            self._validate_all()
            return

        if options["graph_pk"] is None:
            raise CommandError("Provide a graph_pk, or pass --all.")
        try:
            graph = CausalGraph.objects.select_related(
                "document", "schema_version", "ontology_snapshot"
            ).get(pk=options["graph_pk"])
        except CausalGraph.DoesNotExist:
            raise CommandError(f"Graph {options['graph_pk']} not found")

        if not self._validate_one(graph, prefix=""):
            raise CommandError("Validation failed")

    def _validate_all(self) -> None:
        graphs = CausalGraph.objects.select_related(
            "document", "schema_version", "ontology_snapshot"
        ).order_by("pk")
        total = graphs.count()
        if total == 0:
            self.stdout.write("No graphs to validate.")
            return

        failed = 0
        for graph in graphs:
            if not self._validate_one(graph, prefix=f"Graph {graph.pk}: "):
                failed += 1

        summary = f"Validated {total} graph(s), {failed} failed."
        if failed:
            self.stdout.write(self.style.ERROR(summary))
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))

    def _validate_one(self, graph, *, prefix: str) -> bool:
        is_valid, messages = validate_graph(graph)
        for msg in messages:
            self.stdout.write(f"{prefix}{msg}")

        if is_valid:
            self.stdout.write(self.style.SUCCESS(f"{prefix}Valid"))
        else:
            self.stdout.write(self.style.ERROR(f"{prefix}Validation failed"))
        return is_valid
