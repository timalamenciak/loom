"""Backfill canonical_markdown for documents that have a PDF but no markdown yet."""

from django.core.management.base import BaseCommand

from apps.documents.services import extract_markdown_from_pdf
from apps.projects.models import Document


class Command(BaseCommand):
    help = "Extract docling Markdown from uploaded PDFs (backfill or refresh)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-extract even when canonical_markdown already exists.",
        )
        parser.add_argument(
            "--document",
            type=int,
            metavar="PK",
            help="Process only the document with this primary key.",
        )

    def handle(self, *args, **options):
        try:
            from docling.document_converter import DocumentConverter  # noqa: F401
        except ImportError:
            self.stderr.write(
                self.style.ERROR(
                    "docling is not installed. Run: pip install docling"
                )
            )
            return

        qs = Document.objects.filter(pdf_file__isnull=False).exclude(pdf_file="")
        if options["document"]:
            qs = qs.filter(pk=options["document"])
        if not options["force"]:
            qs = qs.filter(canonical_markdown__isnull=True)

        total = qs.count()
        if total == 0:
            self.stdout.write("Nothing to process.")
            return

        self.stdout.write(f"Processing {total} document(s)…")
        ok = skip = 0
        for doc in qs.iterator():
            if extract_markdown_from_pdf(doc):
                ok += 1
                self.stdout.write(f"  ✓  [{doc.pk}] {doc.title[:70]}")
            else:
                skip += 1
                self.stderr.write(f"  ✗  [{doc.pk}] {doc.title[:70]}")

        self.stdout.write(self.style.SUCCESS(f"Done: {ok} extracted, {skip} failed."))
