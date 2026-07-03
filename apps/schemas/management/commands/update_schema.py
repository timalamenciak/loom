"""
python manage.py update_schema [--to-version vX.Y.Z] [--activate] [--yes]

Downloads a CAMO schema release from causalmosaic's GitHub Releases, loads it
into the database (via the existing load_schema_path service — same
dedupe-by-sha256 + cache-invalidation path `load_schema` uses), and
optionally activates it.

Confirmation prompts (unless --yes / --prune-old, see below):
  - before activating a downloaded schema (this changes what every annotator
    sees immediately)
  - before pruning the *previous* active version's on-disk YAML file — this
    NEVER deletes a SchemaVersion database row (graphs stay pinned to their
    row regardless, for export reproducibility); it only tidies up
    config/schema/ once the content is safely persisted in the DB. Pruning
    always requires its own explicit confirmation (--yes only bypasses the
    activation prompt, not this one) unless --prune-old is also passed.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.annotation.models import CausalGraph
from apps.export.management.commands.migrate_graph import _slot_names
from apps.schemas.models import SchemaVersion
from apps.schemas.schema_engine import invalidate_cache
from apps.schemas.services import load_schema_path
from apps.schemas.upstream import (
    UpstreamCheckError,
    download_asset,
    get_latest_release,
    get_release_by_tag,
)


class Command(BaseCommand):
    help = (
        "Download and load a CAMO schema release from causalmosaic's GitHub Releases."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--to-version",
            dest="to_version",
            help="Release tag to fetch, e.g. v0.7.2 (defaults to the latest release)",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            default=False,
            help="Activate the downloaded schema after loading it",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            default=False,
            help="Skip the activation confirmation prompt (non-interactive use)",
        )
        parser.add_argument(
            "--prune-old",
            action="store_true",
            default=False,
            help=(
                "Also skip the prune confirmation and delete the previous "
                "active version's on-disk YAML file (never its DB row) if "
                "no graph still references it"
            ),
        )

    def handle(self, *args, **options):
        try:
            if options["to_version"]:
                release = get_release_by_tag(options["to_version"])
            else:
                release = get_latest_release()
        except UpstreamCheckError as exc:
            raise CommandError(str(exc))

        asset = release.schema_asset()
        if asset is None:
            raise CommandError(
                f"Release {release.tag_name} has no attached .yaml schema asset."
            )

        try:
            content = download_asset(asset)
        except UpstreamCheckError as exc:
            raise CommandError(str(exc))

        target_path = (
            Path(settings.BASE_DIR)
            / "config"
            / "schema"
            / f"camo-{release.version}.yaml"
        )
        target_path.write_text(content, encoding="utf-8")
        self.stdout.write(f"Wrote {target_path.relative_to(settings.BASE_DIR)}")

        old_active = SchemaVersion.get_active()
        schema, created = load_schema_path(target_path, version=release.version)
        self.stdout.write(
            f"{'Loaded' if created else 'Already present:'} CAMO {schema.version} "
            f"(pk={schema.pk}, sha256={schema.sha256[:12]}…)"
        )

        if old_active is not None and old_active.pk != schema.pk:
            old_slots = _slot_names(old_active)
            new_slots = _slot_names(schema)
            added = new_slots - old_slots
            removed = old_slots - new_slots
            if added:
                self.stdout.write(f"  + added slots: {', '.join(sorted(added))}")
            if removed:
                self.stdout.write(f"  - removed slots: {', '.join(sorted(removed))}")

        if not options["activate"]:
            return

        if not options["yes"]:
            confirm = input(
                f"Activate CAMO {schema.version} now? This changes what every "
                "annotator sees immediately. [y/N] "
            )
            if confirm.strip().lower() != "y":
                self.stdout.write("Not activated.")
                return

        schema.is_active = True
        schema.save(update_fields=["is_active"])
        invalidate_cache()
        self.stdout.write(self.style.SUCCESS(f"Activated CAMO {schema.version}."))

        if old_active is None or old_active.pk == schema.pk:
            return

        still_referenced = CausalGraph.objects.filter(
            schema_version=old_active
        ).exists()
        if still_referenced:
            self.stdout.write(
                f"(CAMO {old_active.version}'s on-disk file is kept — "
                "graphs still reference it)"
            )
            return

        old_path = (
            Path(settings.BASE_DIR)
            / "config"
            / "schema"
            / f"camo-{old_active.version}.yaml"
        )
        if not old_path.exists():
            return

        prune = options["prune_old"]
        if not prune:
            confirm = input(
                f"Prune previous version's on-disk file {old_path.name}? "
                "The database row is kept regardless. [y/N] "
            )
            prune = confirm.strip().lower() == "y"

        if prune:
            old_path.unlink()
            self.stdout.write(f"Removed {old_path.relative_to(settings.BASE_DIR)}")
        else:
            self.stdout.write("Not pruned.")
