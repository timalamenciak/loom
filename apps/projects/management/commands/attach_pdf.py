from django.core.management.base import BaseCommand, CommandError

from apps.projects.models import Document
from apps.projects.services import attach_pdf_to_document


class Command(BaseCommand):
    help = "Attach a PDF file to an existing document."

    def add_arguments(self, parser):
        parser.add_argument("document_id", type=int, help="Document primary key")
        parser.add_argument("pdf_file", help="Path to the PDF file")

    def handle(self, *args, **options):
        try:
            doc = Document.objects.select_related("project").get(
                pk=options["document_id"]
            )
        except Document.DoesNotExist:
            raise CommandError(f"No document with id {options['document_id']}.")

        try:
            with open(options["pdf_file"], "rb") as f:
                attach_pdf_to_document(doc, f, options["pdf_file"])
        except FileNotFoundError:
            raise CommandError(f"File not found: {options['pdf_file']}")

        self.stdout.write(
            self.style.SUCCESS(f"Attached PDF to document #{doc.pk}: {doc.title[:60]}")
        )
