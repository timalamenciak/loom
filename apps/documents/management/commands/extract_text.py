from django.core.management.base import BaseCommand, CommandError

from apps.projects.models import Document


class Command(BaseCommand):
    help = "Extract canonical text from document PDFs using pdfplumber."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--document", type=int, metavar="ID", help="Single document ID")
        group.add_argument("--project", type=int, metavar="ID", help="All PDF docs in project")
        group.add_argument("--all", action="store_true", help="All PDFs without canonical_text")

    def handle(self, *args, **options):
        from apps.documents.services import extract_text_from_pdf

        if options["document"]:
            docs = Document.objects.filter(pk=options["document"])
            if not docs.exists():
                raise CommandError(f"Document {options['document']} not found.")
        elif options["project"]:
            docs = Document.objects.filter(
                project_id=options["project"],
                pdf_file__isnull=False,
            ).exclude(pdf_file="")
        else:
            docs = Document.objects.filter(
                pdf_file__isnull=False,
                canonical_text__isnull=True,
            ).exclude(pdf_file="")

        total = ok = 0
        for doc in docs:
            total += 1
            if extract_text_from_pdf(doc):
                ok += 1
                chars = len(doc.canonical_text or "")
                pages = len(doc.page_map or [])
                self.stdout.write(f"  ✓ [{doc.pk}] {doc.title[:60]}  ({chars} chars, {pages} pages)")
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ✗ [{doc.pk}] {doc.title[:60]}  — no PDF or extraction failed"
                    )
                )

        self.stdout.write(self.style.SUCCESS(f"\n{ok}/{total} documents extracted."))
