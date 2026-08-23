"""
python manage.py check_all_updates

Runs the schema + ontology update checks and persists results to
UpdateCheckRecord, then prints a summary table. Unlike check_schema_updates /
check_ontology_updates this always exits 0 — it's meant for a scheduled task
(cron, Celery beat) to call unattended; the admin notification banner reads
UpdateCheckRecord, not this command's exit code.
"""

from django.core.management.base import BaseCommand

from apps.schemas.models import UpdateCheckRecord
from apps.schemas.update_service import check_all_updates


class Command(BaseCommand):
    help = "Check for schema and ontology updates and persist results to UpdateCheckRecord."

    def handle(self, *args, **options):
        check_all_updates()

        records = UpdateCheckRecord.objects.order_by("module_type", "module_name")
        if not records:
            self.stdout.write("No update-checkable modules found.")
            return

        header = (
            f"{'MODULE':<10} {'NAME':<20} {'CURRENT':<15} "
            f"{'AVAILABLE':<15} {'UPDATE?':<8} CHECKED"
        )
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for record in records:
            flag = "yes" if record.is_update_available else "no"
            line = (
                f"{record.module_type:<10} {record.module_name:<20} "
                f"{record.current_version:<15} {record.available_version or '-':<15} "
                f"{flag:<8} {record.checked_at:%Y-%m-%d %H:%M}"
            )
            style = (
                self.style.WARNING if record.is_update_available else self.style.SUCCESS
            )
            self.stdout.write(style(line))
