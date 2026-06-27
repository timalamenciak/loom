import time

from django.core.management.base import BaseCommand

from apps.ontology.models import OntologyLoadRequest
from apps.ontology.project_service import process_load_request


class Command(BaseCommand):
    help = "Process queued project ontology loads. Use --watch to run continuously."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=int, default=5)

    def handle(self, *args, **options):
        while True:
            request = (
                OntologyLoadRequest.objects.filter(
                    status=OntologyLoadRequest.STATUS_PENDING
                )
                .order_by("created_at")
                .first()
            )
            if request:
                self.stdout.write(f"Processing ontology load #{request.pk}")
                process_load_request(request)
                request.refresh_from_db()
                self.stdout.write(f"Ontology load #{request.pk}: {request.status}")
            elif not options["watch"]:
                break
            else:
                time.sleep(max(1, options["interval"]))
