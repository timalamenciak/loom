"""
python manage.py validate_graph <graph_pk>
"""

import yaml
from django.core.management.base import BaseCommand, CommandError

from apps.annotation.models import CausalGraph
from apps.export.serializer import build_provenance, serialize_graph
from apps.export.validators import validate_graph_data


class Command(BaseCommand):
    help = "Validate a CausalGraph against the active LinkML schema"

    def add_arguments(self, parser):
        parser.add_argument("graph_pk", type=int, help="Primary key of the graph")

    def handle(self, *args, **options):
        try:
            graph = CausalGraph.objects.select_related(
                "document", "schema_version"
            ).get(pk=options["graph_pk"])
        except CausalGraph.DoesNotExist:
            raise CommandError(f"Graph {options['graph_pk']} not found")

        data = serialize_graph(graph)
        pre_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=True)
        prov = build_provenance(graph, pre_yaml.encode())
        data["provenance"] = prov

        is_valid, messages = validate_graph_data(data, graph.schema_version.linkml_yaml)
        for msg in messages:
            self.stdout.write(msg)

        if is_valid:
            self.stdout.write(self.style.SUCCESS("Valid"))
        else:
            self.stdout.write(self.style.ERROR("Validation failed"))
            raise CommandError("Validation failed")
