from django.core.management.base import BaseCommand

from apps.schemas.models import SchemaVersion


class Command(BaseCommand):
    help = "List all loaded CAMO schema versions."

    def handle(self, *args, **options):
        versions = SchemaVersion.objects.all()
        if not versions:
            self.stdout.write(
                "No schemas loaded. Run: python manage.py load_schema <file.yaml> --activate"
            )
            return
        for sv in versions:
            active = " [ACTIVE]" if sv.is_active else ""
            self.stdout.write(
                f"  #{sv.pk}  CAMO {sv.version}{active}  sha256={sv.sha256[:12]}…  loaded={sv.loaded_at:%Y-%m-%d %H:%M}"
            )
