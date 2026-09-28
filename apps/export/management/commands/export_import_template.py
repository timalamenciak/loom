"""
python manage.py export_import_template <graph_pk> -o template.xlsx

Thin wrapper around write_graph_xlsx(graph, blank=True) — the same writer
the web "Download blank template" link (ExportExcelView with ?blank=1)
uses, so the template always matches whatever schema version the project
is pinned to.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.annotation.models import CausalGraph
from apps.export.import_excel import write_graph_xlsx


class Command(BaseCommand):
    help = "Write a blank, schema-driven Excel import template for a graph."

    def add_arguments(self, parser):
        parser.add_argument("graph_pk", type=int, help="Primary key of the graph")
        parser.add_argument("-o", "--output", required=True, help="Output .xlsx path")

    def handle(self, *args, **options):
        try:
            graph = CausalGraph.objects.select_related(
                "schema_version", "document__project"
            ).get(pk=options["graph_pk"])
        except CausalGraph.DoesNotExist:
            raise CommandError(f"No graph with id {options['graph_pk']}.")

        content = write_graph_xlsx(graph, blank=True)
        with open(options["output"], "wb") as f:
            f.write(content)

        self.stdout.write(self.style.SUCCESS(f"Wrote template to {options['output']}"))
