from django.conf import settings
from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_projects",
    )
    active_schema = models.ForeignKey(
        "schemas.SchemaVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="projects",
    )
    ontology_snapshot = models.ForeignKey(
        "ontology.OntologySnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="projects",
    )
    ontology_names = models.JSONField(default=list, blank=True)
    auto_infer_ontologies = models.BooleanField(default=True)
    source_document_rollup = models.JSONField(default=list, blank=True)
    hidden_slots = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def member_role(self, user):
        """Return this user's role string in the project, or None."""
        try:
            return self.memberships.get(user=user).role
        except ProjectMembership.DoesNotExist:
            return None


class ProjectMembership(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_REVIEWER = "reviewer"
    ROLE_ANNOTATOR = "annotator"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_REVIEWER, "Reviewer"),
        (ROLE_ANNOTATOR, "Annotator"),
    ]

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="project_memberships",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_ANNOTATOR)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("project", "user")]
        ordering = ["role", "user__username"]

    def __str__(self):
        return f"{self.user.username} ({self.role}) in {self.project}"


class Document(models.Model):
    SOURCE_PDF_UPLOAD = "pdf_upload"
    SOURCE_RIS_IMPORT = "ris_import"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [
        (SOURCE_PDF_UPLOAD, "PDF Upload"),
        (SOURCE_RIS_IMPORT, "RIS Import"),
        (SOURCE_MANUAL, "Manual"),
    ]

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="documents"
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)

    # PDF — nullable until a file is attached
    pdf_file = models.FileField(upload_to="pdfs/", null=True, blank=True)
    sha256 = models.CharField(max_length=64, null=True, blank=True)
    # Populated by Phase 3 text extraction; for abstract-only records set to abstract
    canonical_text = models.TextField(null=True, blank=True)
    # offset→page/bbox mapping; populated in Phase 3
    page_map = models.JSONField(null=True, blank=True)
    # Markdown extracted by pdfplumber with layout=True (optional; coexists with canonical_text)
    canonical_markdown = models.TextField(null=True, blank=True)

    # Bibliographic fields
    title = models.TextField()
    authors = models.JSONField(default=list)
    year = models.IntegerField(null=True, blank=True)
    doi = models.CharField(max_length=512, null=True, blank=True, db_index=True)
    journal = models.CharField(max_length=512, blank=True)
    abstract = models.TextField(blank=True)
    ris_raw = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "doi"],
                condition=models.Q(doi__isnull=False) & ~models.Q(doi=""),
                name="unique_document_doi_per_project",
            )
        ]

    def __str__(self):
        return self.title[:80]

    @property
    def has_pdf(self):
        return bool(self.pdf_file)

    @property
    def is_annotatable(self):
        return bool(self.canonical_text)

    @property
    def text_source(self):
        if self.pdf_file:
            return "pdf"
        if self.abstract:
            return "abstract"
        return "none"

    @property
    def short_authors(self):
        if not self.authors:
            return ""
        if len(self.authors) == 1:
            return self.authors[0]
        if len(self.authors) == 2:
            return f"{self.authors[0]} & {self.authors[1]}"
        return f"{self.authors[0]} et al."


class Assignment(models.Model):
    STATUS_ASSIGNED = "assigned"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_SUBMITTED = "submitted"
    STATUS_REVIEWED = "reviewed"
    STATUS_RETURNED = "returned"
    STATUS_CHOICES = [
        (STATUS_ASSIGNED, "Assigned"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_REVIEWED, "Reviewed"),
        (STATUS_RETURNED, "Returned"),
    ]
    graph = models.ForeignKey(
        "annotation.CausalGraph",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
    )

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="assignments"
    )
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="assignments"
    )
    annotator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assignments_given",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ASSIGNED
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("document", "annotator")]
        ordering = ["-assigned_at"]

    def __str__(self):
        return f"{self.annotator.username} → {self.document.title[:50]} [{self.status}]"
