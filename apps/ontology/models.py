import hashlib

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models


class OntologyRelease(models.Model):
    """One content-addressed load of a configured ontology, or an ad hoc accumulation.

    ``source_kind="bulk"`` (the default) represents a single OBO/OWL file fetched
    at a point in time and treated as immutable — ``source_sha256`` is the hash of
    that file and never changes after the load completes.

    ``source_kind="wikidata_adhoc"`` represents a per-project accumulation of
    Wikidata terms picked individually by annotators.  ``source_sha256`` is
    recomputed from the sorted set of (curie, label) pairs each time a new term is
    added; it therefore changes with every addition.  This is expected and fine:
    unlike bulk releases, adhoc releases are mutable by design and are not meant to
    be pinned for reproducibility.
    """

    STATUS_LOADING = "loading"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_LOADING, "Loading"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
    ]

    SOURCE_KIND_BULK = "bulk"
    SOURCE_KIND_WIKIDATA_ADHOC = "wikidata_adhoc"
    SOURCE_KIND_CHOICES = [
        (SOURCE_KIND_BULK, "Bulk OBO/OWL load"),
        (SOURCE_KIND_WIKIDATA_ADHOC, "Ad hoc Wikidata picks"),
    ]

    name = models.CharField(max_length=200)
    prefix = models.CharField(max_length=50, db_index=True)
    source_url = models.TextField()
    source_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    # Sorted root CURIEs this release was scoped to at load time (see
    # ontologies.yaml's `root_terms`/`include_descendants`), or [] for an
    # unscoped full-file load. `source_sha256` alone content-addresses the
    # raw upstream file; this field distinguishes releases loaded from the
    # *same* file bytes but indexed to a different branch, so reloading with
    # a new scope doesn't silently reuse a differently-scoped release.
    scope_root_curies = models.JSONField(default=list, blank=True)
    loaded_at = models.DateTimeField(auto_now_add=True)
    term_count = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_LOADING
    )
    error = models.TextField(blank=True)
    source_kind = models.CharField(
        max_length=30,
        choices=SOURCE_KIND_CHOICES,
        default=SOURCE_KIND_BULK,
        db_index=True,
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="wikidata_adhoc_releases",
    )

    class Meta:
        ordering = ["prefix", "-loaded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "prefix"],
                condition=models.Q(source_kind="wikidata_adhoc"),
                name="unique_wikidata_adhoc_per_project_prefix",
            )
        ]

    def __str__(self):
        return f"{self.prefix} ({self.source_sha256[:12] or self.status})"


class OntologySnapshot(models.Model):
    """An immutable manifest of ontology releases pinned by projects/graphs."""

    name = models.CharField(max_length=200)
    built_at = models.DateTimeField(auto_now_add=True)
    source_versions = models.JSONField(default=dict)
    manifest_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    releases = models.ManyToManyField(
        OntologyRelease, related_name="snapshots", blank=True
    )
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["-built_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="ontology_one_active_snapshot",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.built_at:%Y-%m-%d})"

    def save(self, *args, **kwargs):
        if self.is_active:
            OntologySnapshot.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def refresh_manifest(self):
        rows = self.releases.order_by("prefix", "source_sha256").values_list(
            "prefix", "source_sha256"
        )
        manifest = "\n".join(f"{prefix}:{sha}" for prefix, sha in rows)
        self.manifest_sha256 = hashlib.sha256(manifest.encode()).hexdigest()
        self.save(update_fields=["manifest_sha256"])

    @classmethod
    def get_active(cls):
        return cls.objects.filter(is_active=True).first()


class OntologyTerm(models.Model):
    """A term owned by an immutable release (or a legacy snapshot)."""

    snapshot = models.ForeignKey(
        OntologySnapshot,
        on_delete=models.CASCADE,
        related_name="terms",
        null=True,
        blank=True,
    )
    release = models.ForeignKey(
        OntologyRelease,
        on_delete=models.PROTECT,
        related_name="terms",
        null=True,
        blank=True,
    )
    prefix = models.CharField(max_length=50, db_index=True)
    curie = models.CharField(max_length=200)
    label = models.CharField(max_length=1000)
    synonyms = models.JSONField(default=list, blank=True)
    synonym_labels = models.TextField(blank=True)
    definition = models.TextField(blank=True)
    obsolete = models.BooleanField(default=False, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "curie"],
                condition=models.Q(snapshot__isnull=False),
                name="unique_legacy_snapshot_curie",
            ),
            models.UniqueConstraint(
                fields=["release", "curie"],
                condition=models.Q(release__isnull=False),
                name="unique_release_curie",
            ),
        ]
        indexes = [
            models.Index(
                fields=["snapshot", "prefix"], name="ontology_on_snapsho_1680f5_idx"
            ),
            models.Index(
                fields=["snapshot", "curie"], name="ontology_on_snapsho_258343_idx"
            ),
            models.Index(
                fields=["release", "prefix"], name="ontology_release_prefix_idx"
            ),
            models.Index(
                fields=["release", "curie"], name="ontology_release_curie_idx"
            ),
            GinIndex(
                fields=["label"],
                name="ontologyterm_label_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["synonym_labels"],
                name="ontologyterm_synonyms_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.curie} — {self.label}"


class AdHocOntologySource(models.Model):
    """A user-registered OBO/OWL source that supplements config/ontologies.yaml.

    Entries here are discovered by the loader alongside YAML entries.  YAML
    entries take precedence when name or prefix collides.
    """

    prefix = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200, unique=True)
    url = models.URLField(max_length=500)
    description = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registered_ontologies",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["prefix"]

    def __str__(self):
        return f"{self.prefix} ({self.name})"


class OntologyTermSuggestion(models.Model):
    """A term an annotator typed as free text because no cached term matched.

    Logged for a curator to periodically batch and file upstream (e.g. as an
    ELMO GitHub issue, an OBO Foundry tracker issue, or a new Wikidata item).
    This is Loom-side curation workflow metadata — it is never exported as
    part of a CAMO instance graph.
    """

    STATUS_PENDING = "pending"
    STATUS_SUBMITTED = "submitted_upstream"
    STATUS_REJECTED = "rejected"
    STATUS_RESOLVED = "resolved"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUBMITTED, "Submitted upstream"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_RESOLVED, "Resolved"),
    ]

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="ontology_term_suggestions",
    )
    graph = models.ForeignKey(
        "annotation.CausalGraph",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ontology_term_suggestions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ontology_term_suggestions",
    )
    slot_name = models.CharField(max_length=200, blank=True)
    label = models.CharField(max_length=1000)
    suggested_parent = models.CharField(max_length=500, blank=True)
    definition = models.TextField(blank=True)
    target_ontology = models.CharField(max_length=100)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    upstream_issue_url = models.URLField(max_length=500, blank=True)
    reviewer_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} -> {self.target_ontology} [{self.status}]"


class OntologyLoadRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETE = "complete"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETE, "Complete"),
        (STATUS_FAILED, "Failed"),
    ]

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="ontology_load_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ontology_load_requests",
    )
    ontology_names = models.JSONField(default=list)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Ontology load for {self.project} [{self.status}]"


class OntologyLoadItem(models.Model):
    """Per-ontology progress for a project load request."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETE = "complete"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = OntologyLoadRequest.STATUS_CHOICES

    request = models.ForeignKey(
        OntologyLoadRequest,
        on_delete=models.CASCADE,
        related_name="items",
    )
    name = models.CharField(max_length=200)
    prefix = models.CharField(max_length=50)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    term_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["request", "name"], name="unique_ontology_load_item"
            )
        ]

    def __str__(self):
        return f"{self.name} for request {self.request_id} [{self.status}]"
