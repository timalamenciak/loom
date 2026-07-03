"""
python manage.py check_schema_updates

Polls causalmosaic's GitHub Releases for a CAMO schema newer than Loom's
active SchemaVersion and prints a structural diff. Never writes to the
database or filesystem — see update_schema for actually fetching a new
version.

This is an opt-in admin convenience, not something any request path depends
on: Loom targets network-restricted deployments, so a failed network check
here just prints a warning and exits, it never raises past this command.

Exit codes: 0 = up to date, 1 = update available, 2 = couldn't check.
"""

from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError

from apps.export.management.commands.migrate_graph import _enum_values, _slot_names
from apps.schemas.models import SchemaVersion
from apps.schemas.upstream import (
    UpstreamCheckError,
    download_asset,
    get_latest_release,
    version_tuple,
)


class Command(BaseCommand):
    help = "Check causalmosaic's GitHub Releases for a CAMO schema newer than Loom's active version."

    def handle(self, *args, **options):
        active = SchemaVersion.get_active()
        if active is None:
            raise CommandError(
                "No active SchemaVersion. Load one first with "
                "`manage.py load_schema <path> --activate`."
            )

        try:
            release = get_latest_release()
        except UpstreamCheckError as exc:
            self.stdout.write(self.style.WARNING(f"Could not check for updates: {exc}"))
            self.stdout.write(
                "(this is expected in network-restricted deployments — "
                "check_schema_updates is an opt-in convenience, not required)"
            )
            raise SystemExit(2)

        if version_tuple(release.version) <= version_tuple(active.version):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Up to date: Loom's active schema is {active.version}; "
                    f"causalmosaic's latest release is {release.version}."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"Update available: Loom is on {active.version}; "
                f"causalmosaic's latest release is {release.version} "
                f"(tag {release.tag_name})."
            )
        )

        asset = release.schema_asset()
        if asset is None:
            self.stdout.write(
                "(release has no attached .yaml schema asset — nothing to diff)"
            )
            raise SystemExit(1)

        try:
            new_content = download_asset(asset)
        except UpstreamCheckError as exc:
            self.stdout.write(
                self.style.WARNING(f"Could not download {asset.name}: {exc}")
            )
            raise SystemExit(2)

        new_stub = SimpleNamespace(linkml_yaml=new_content)
        old_slots = _slot_names(active)
        new_slots = _slot_names(new_stub)
        added_slots = new_slots - old_slots
        removed_slots = old_slots - new_slots

        self.stdout.write("")
        if added_slots:
            self.stdout.write(f"Added slots ({len(added_slots)}):")
            for slot in sorted(added_slots):
                self.stdout.write(f"  + {slot}")
        if removed_slots:
            self.stdout.write(f"Removed slots ({len(removed_slots)}):")
            for slot in sorted(removed_slots):
                self.stdout.write(f"  - {slot}")

        old_enums = _enum_values(active)
        new_enums = _enum_values(new_stub)
        changed_enums = [
            name
            for name in old_enums
            if name in new_enums and old_enums[name] != new_enums[name]
        ]
        added_enums = set(new_enums) - set(old_enums)
        removed_enums = set(old_enums) - set(new_enums)
        if added_enums or removed_enums or changed_enums:
            self.stdout.write(
                f"Enum changes: {len(added_enums)} added, "
                f"{len(removed_enums)} removed, {len(changed_enums)} changed"
            )

        if release.body:
            self.stdout.write("\nRelease notes:")
            self.stdout.write(release.body)

        self.stdout.write(
            "\nRun `manage.py update_schema --to-version "
            f"{release.tag_name}` to fetch and load this version."
        )
        raise SystemExit(1)
