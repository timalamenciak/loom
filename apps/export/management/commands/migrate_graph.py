"""
python manage.py migrate_graph <graph_pk> --to-version 0.5.0 --report

Diffs two SchemaVersions and reports migration impact on a specific graph.
Prints added/removed slots, changed enum values, and which nodes/edges carry
data for affected fields.  Does not modify the graph data (--report only for now).
"""

from django.core.management.base import BaseCommand, CommandError

from apps.annotation.models import CausalGraph
from apps.schemas.models import SchemaVersion


def _slot_names(sv):
    from linkml_runtime.utils.schemaview import SchemaView
    schema = SchemaView(sv.linkml_yaml)
    return set(schema.all_slots().keys())


def _enum_values(sv):
    from linkml_runtime.utils.schemaview import SchemaView
    schema = SchemaView(sv.linkml_yaml)
    return {
        name: set(enum.permissible_values.keys())
        for name, enum in schema.all_enums().items()
    }


def _has_value(data: dict, slot: str) -> bool:
    """True if the slot (possibly nested with __) has a non-empty value in data."""
    if "__" in slot:
        parent, child = slot.split("__", 1)
        nested = data.get(parent)
        if isinstance(nested, dict):
            v = nested.get(child)
            return v is not None and v != "" and v != []
        return False
    v = data.get(slot)
    return v is not None and v != "" and v != []


class Command(BaseCommand):
    help = "Report migration impact when upgrading a graph to a new schema version"

    def add_arguments(self, parser):
        parser.add_argument("graph_pk", type=int, help="Primary key of the graph")
        parser.add_argument(
            "--to-version",
            required=True,
            help="Target schema version string (e.g. 0.5.0)",
        )
        parser.add_argument(
            "--report",
            action="store_true",
            default=True,
            help="Print a migration report (default; no data is changed)",
        )

    def handle(self, *args, **options):
        try:
            graph = CausalGraph.objects.select_related(
                "document", "schema_version"
            ).get(pk=options["graph_pk"])
        except CausalGraph.DoesNotExist:
            raise CommandError(f"Graph {options['graph_pk']} not found")

        old_sv = graph.schema_version
        try:
            new_sv = SchemaVersion.objects.get(version=options["to_version"])
        except SchemaVersion.DoesNotExist:
            raise CommandError(
                f"Schema version '{options['to_version']}' not found in the database. "
                f"Load it first with: manage.py load_schema <file>"
            )

        if old_sv.pk == new_sv.pk:
            self.stdout.write(self.style.WARNING("Graph is already on this schema version."))
            return

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Migration Report")
        self.stdout.write(f"{'='*60}")
        self.stdout.write(f"Graph    : {graph.pk} — {graph.document.title[:60]}")
        self.stdout.write(f"From     : {old_sv.version}")
        self.stdout.write(f"To       : {new_sv.version}")
        self.stdout.write("")

        old_slots = _slot_names(old_sv)
        new_slots = _slot_names(new_sv)
        added_slots = new_slots - old_slots
        removed_slots = old_slots - new_slots

        if added_slots:
            self.stdout.write(f"Added slots ({len(added_slots)}):")
            for s in sorted(added_slots):
                self.stdout.write(f"  + {s}")
        else:
            self.stdout.write("Added slots: none")

        self.stdout.write("")

        if removed_slots:
            self.stdout.write(f"Removed slots ({len(removed_slots)}):")
            for s in sorted(removed_slots):
                self.stdout.write(f"  - {s}")
        else:
            self.stdout.write("Removed slots: none")

        self.stdout.write("")

        # Enum value changes
        old_enums = _enum_values(old_sv)
        new_enums = _enum_values(new_sv)
        enum_changes = []
        for enum_name in old_enums:
            if enum_name not in new_enums:
                enum_changes.append((enum_name, old_enums[enum_name], set()))
                continue
            added_vals = new_enums[enum_name] - old_enums[enum_name]
            removed_vals = old_enums[enum_name] - new_enums[enum_name]
            if added_vals or removed_vals:
                enum_changes.append((enum_name, removed_vals, added_vals))

        if enum_changes:
            self.stdout.write(f"Enum changes ({len(enum_changes)}):")
            for name, removed_vals, added_vals in enum_changes:
                self.stdout.write(f"  {name}:")
                for v in sorted(removed_vals):
                    self.stdout.write(f"    - {v}")
                for v in sorted(added_vals):
                    self.stdout.write(f"    + {v}")
        else:
            self.stdout.write("Enum changes: none")

        self.stdout.write("")

        # Impact on this graph's nodes and edges
        affected_nodes = []
        for node in graph.nodes.all():
            hits = [s for s in removed_slots if _has_value(node.data, s)]
            if hits:
                affected_nodes.append((node, hits))

        affected_edges = []
        for edge in graph.edges.all():
            hits = [s for s in removed_slots if _has_value(edge.data, s)]
            if hits:
                affected_edges.append((edge, hits))

        if affected_nodes:
            self.stdout.write(f"Affected nodes ({len(affected_nodes)}):")
            for node, slots in affected_nodes:
                self.stdout.write(f"  {node.name}: {', '.join(slots)}")
        else:
            self.stdout.write("Affected nodes: none")

        self.stdout.write("")

        if affected_edges:
            self.stdout.write(f"Affected edges ({len(affected_edges)}):")
            for edge, slots in affected_edges:
                self.stdout.write(
                    f"  {edge.subject.name} →[{edge.predicate}]→ {edge.object.name}: "
                    f"{', '.join(slots)}"
                )
        else:
            self.stdout.write("Affected edges: none")

        self.stdout.write("")
        if removed_slots or enum_changes or affected_nodes or affected_edges:
            self.stdout.write(
                self.style.WARNING(
                    "Action required: review removed slots and enum value changes above "
                    "before upgrading this graph."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("No breaking changes — safe to migrate."))
        self.stdout.write("")
