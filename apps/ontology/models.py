from django.db import models


class OntologySnapshot(models.Model):
    """A versioned snapshot of one or more loaded ontologies.

    Projects pin a snapshot so exports can record which term set was used.
    A new snapshot is created each time load_ontology runs.
    """

    name = models.CharField(max_length=200)
    built_at = models.DateTimeField(auto_now_add=True)
    source_versions = models.JSONField(default=dict)  # {prefix: {url, term_count, loaded_at}}
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["-built_at"]

    def __str__(self):
        return f"{self.name} ({self.built_at:%Y-%m-%d})"

    def save(self, *args, **kwargs):
        if self.is_active:
            OntologySnapshot.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_active(cls):
        return cls.objects.filter(is_active=True).first()


class OntologyTerm(models.Model):
    """A single term from an OBO/OWL ontology, indexed for fuzzy search.

    search_text is a pre-computed concatenation of label + synonyms so a
    single icontains query covers both (avoids JOINs or complex JSON ops).
    Production deployments should add a GIN trgm index on label and
    search_text: run `python manage.py create_trgm_index`.
    """

    snapshot = models.ForeignKey(
        OntologySnapshot,
        on_delete=models.CASCADE,
        related_name="terms",
    )
    prefix = models.CharField(max_length=50, db_index=True)   # e.g. ENVO, NCBITaxon
    curie = models.CharField(max_length=200)                   # e.g. ENVO:00001001
    label = models.CharField(max_length=1000)
    synonyms = models.JSONField(default=list, blank=True)      # list of str
    synonym_labels = models.TextField(blank=True)              # space-joined synonyms for search
    definition = models.TextField(blank=True)
    obsolete = models.BooleanField(default=False, db_index=True)

    class Meta:
        unique_together = [("snapshot", "curie")]
        indexes = [
            models.Index(fields=["snapshot", "prefix"]),
            models.Index(fields=["snapshot", "curie"]),
        ]

    def __str__(self):
        return f"{self.curie} — {self.label}"
