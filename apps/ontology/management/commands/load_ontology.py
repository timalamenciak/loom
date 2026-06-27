from django.core.management.base import BaseCommand, CommandError

from apps.ontology.loaders import (
    get_or_create_active_snapshot,
    list_ontology_names,
    load_ontology,
    preload_names,
)
from apps.ontology.models import OntologySnapshot


class Command(BaseCommand):
    help = "Load one or more ontologies into the active OntologySnapshot."

    def add_arguments(self, parser):
        parser.add_argument(
            "names",
            nargs="*",
            metavar="NAME",
            help="Ontology name(s) from config/ontologies.yaml (e.g. envo pato)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Load all ontologies listed in the config",
        )
        parser.add_argument(
            "--preload",
            action="store_true",
            help="Load only the preload subset defined in config/ontologies.yaml",
        )
        parser.add_argument(
            "--new-snapshot",
            action="store_true",
            help="Create a fresh snapshot instead of adding to the active one",
        )
        parser.add_argument(
            "--source",
            metavar="URL_OR_PATH",
            help="Override the configured source URL/path for a single ontology",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            default=True,
            help="Mark the snapshot as active after loading (default: True)",
        )

    def handle(self, *args, **options):
        names = options["names"]

        if options["all"]:
            names = list_ontology_names()
        elif options["preload"]:
            names = preload_names()
        elif not names:
            self.stdout.write(
                "Available ontologies: " + ", ".join(list_ontology_names())
            )
            self.stdout.write("Preload set: " + ", ".join(preload_names()))
            return

        if options["new_snapshot"] or not OntologySnapshot.get_active():
            snapshot = OntologySnapshot.objects.create(
                name="snapshot-" + "-".join(names),
                is_active=bool(options["activate"]),
            )
            self.stdout.write(f"Created new snapshot: {snapshot}")
        else:
            snapshot = get_or_create_active_snapshot()
            self.stdout.write(f"Using active snapshot: {snapshot}")

        source_override = options.get("source")
        if source_override and len(names) > 1:
            raise CommandError("--source can only be used with a single ontology name.")

        total_terms = 0
        for name in names:
            self.stdout.write(f"Loading {name} …")
            try:
                snapshot, count = load_ontology(
                    name,
                    source=source_override,
                    snapshot=snapshot,
                    stdout=self.stdout,
                )
                self.stdout.write(self.style.SUCCESS(f"  {name}: {count:,} terms"))
                total_terms += count
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"  {name}: FAILED — {exc}"))

        if options["activate"]:
            snapshot.is_active = True
            snapshot.save(update_fields=["is_active"])

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. {total_terms:,} terms in snapshot {snapshot.pk}."
            )
        )
