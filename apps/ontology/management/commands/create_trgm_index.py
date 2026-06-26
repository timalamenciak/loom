"""Create GIN trigram indexes on OntologyTerm for production search speed.

Requires PostgreSQL pg_trgm extension. Run once after initial setup:
    python manage.py create_trgm_index
"""

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Create pg_trgm GIN indexes on OntologyTerm.label and synonym_labels."

    def handle(self, *args, **options):
        with connection.cursor() as cur:
            self.stdout.write("Creating pg_trgm extension …")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

            table = "ontology_ontologyterm"

            for col, idx in [
                ("label", "ontologyterm_label_trgm_idx"),
                ("synonym_labels", "ontologyterm_synonyms_trgm_idx"),
            ]:
                self.stdout.write(f"Creating GIN trgm index on {col} …")
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx} "
                    f"ON {table} USING GIN ({col} gin_trgm_ops);"
                )

        self.stdout.write(
            self.style.SUCCESS(
                "GIN trigram indexes created. Ontology search is now fast."
            )
        )
