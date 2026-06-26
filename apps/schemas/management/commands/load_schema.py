from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.schemas.models import SchemaVersion
from apps.schemas.schema_engine import invalidate_cache


class Command(BaseCommand):
    help = "Load a CAMO LinkML YAML file into the database and optionally activate it."

    def add_arguments(self, parser):
        parser.add_argument("yaml_file", help="Path to the .yaml schema file")
        parser.add_argument(
            "--activate",
            action="store_true",
            default=False,
            help="Set this schema as the active version immediately",
        )
        parser.add_argument(
            "--schema-version",
            dest="version",
            help="Override the version string (defaults to the 'version:' field in the YAML)",
        )

    def handle(self, *args, **options):
        path = Path(options["yaml_file"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        content = path.read_text(encoding="utf-8")

        # Extract version from YAML if not overridden
        version = options.get("version")
        if not version:
            import yaml

            try:
                doc = yaml.safe_load(content)
                version = str(doc.get("version", path.stem))
            except Exception:
                version = path.stem

        # Quick parse check via linkml-runtime
        try:
            from linkml_runtime.utils.schemaview import SchemaView

            SchemaView(content)
        except Exception as exc:
            raise CommandError(f"Invalid LinkML schema: {exc}") from exc

        sv = SchemaVersion.objects.create(
            version=version,
            linkml_yaml=content,
            is_active=options["activate"],
        )

        invalidate_cache()

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded CAMO {sv.version} (pk={sv.pk}, sha256={sv.sha256[:12]}…)"
                + (" — set as active" if sv.is_active else "")
            )
        )
