"""Export a graph after mandatory LinkML validation."""

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
            help="Deprecated compatibility flag; validation is always performed",
        )
        parser.add_argument(
            "-o",
            "--output",
            type=str,
            help="Output file path (default: stdout)",
        )

    def handle(self, *args, **options):
        try:
            graph = CausalGraph.objects.select_related(
                "document", "schema_version", "ontology_snapshot"
            ).get(pk=options["graph_pk"])
        except CausalGraph.DoesNotExist:
            raise CommandError(f"Graph {options['graph_pk']} not found")

        data = serialize_graph(graph)
        pre_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=True)
        prov = build_provenance(graph, pre_yaml.encode())
        data["provenance"] = prov
        final_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

        is_valid, messages = validate_graph_data(
            data, graph.schema_version.linkml_yaml
        )
        if not is_valid:
            for msg in messages:
                self.stderr.write(msg)
            raise CommandError("Validation failed — export aborted")
        for msg in messages:
            self.stderr.write(self.style.WARNING(msg))

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
