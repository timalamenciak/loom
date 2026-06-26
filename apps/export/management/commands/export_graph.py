"""
python manage.py export_graph <graph_pk> [--validate] [-o out.yaml]
"""

import yaml
from django.core.management.base import BaseCommand, CommandError

from apps.annotation.models import CausalGraph
from apps.export.serializer import build_provenance, serialize_graph
from apps.export.validators import validate_graph_data


class Command(BaseCommand):
    help = "Export a CausalGraph to YAML (CAMO schema)"

    def add_arguments(self, parser):
        parser.add_argument("graph_pk", type=int, help="Primary key of the graph")
        parser.add_argument(
            "--validate",
            action="store_true",
            help="Validate against the active LinkML schema before writing",
        )
        parser.add_argument(
            "-o", "--output",
            type=str,
            help="Output file path (default: stdout)",
        )

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
        final_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

        if options["validate"]:
            is_valid, messages = validate_graph_data(data, graph.schema_version.linkml_yaml)
            for msg in messages:
                self.stdout.write(msg)
            if not is_valid:
                raise CommandError("Validation failed — export aborted")

        if options.get("output"):
            with open(options["output"], "w", encoding="utf-8") as f:
                f.write(final_yaml)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Graph {graph.pk} exported to {options['output']} "
                    f"(SHA-256: {prov['export_sha256'][:16]}...)"
                )
            )
        else:
            self.stdout.write(final_yaml)
