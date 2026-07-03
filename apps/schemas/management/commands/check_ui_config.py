from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.schemas.models import SchemaVersion
from apps.schemas.schema_engine import get_schema_view
from apps.schemas.ui_config import check_ui_config_drift


class Command(BaseCommand):
    help = (
        "Warn about config/loom_ui.yaml entries (layers, ontology_routing, "
        "widget_overrides) that no longer match a slot on the active schema."
    )

    def handle(self, *args, **options):
        schema = SchemaVersion.get_active()
        if schema is None:
            raise CommandError(
                "No active SchemaVersion. Load one with "
                "`manage.py load_schema <path> --activate` first."
            )

        ui_config_path = Path(settings.BASE_DIR) / "config" / "loom_ui.yaml"
        ui_config = yaml.safe_load(ui_config_path.read_text(encoding="utf-8"))

        warnings = check_ui_config_drift(get_schema_view(schema), ui_config)
        if not warnings:
            self.stdout.write(
                self.style.SUCCESS(
                    f"config/loom_ui.yaml matches CAMO {schema.version}."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"{len(warnings)} loom_ui.yaml drift warning(s) against "
                f"CAMO {schema.version}:"
            )
        )
        for warning in warnings:
            self.stdout.write(f"  - {warning}")
