import uuid

from django.conf import settings
from django.db import models


def _new_uuid():
    return str(uuid.uuid4())


class WorkSession(models.Model):
    """Active-time tracking for a single annotation sitting."""

    SOURCE_AUTO = "auto"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [
        (SOURCE_AUTO, "Auto"),
        (SOURCE_MANUAL, "Manual"),
    ]

    assignment = models.ForeignKey(
        "projects.Assignment",
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    annotator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="work_sessions",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    active_seconds = models.IntegerField(default=0)
    idle_seconds = models.IntegerField(default=0)
    open_seconds = models.IntegerField(default=0)
    source = models.CharField(
        max_length=10, choices=SOURCE_CHOICES, default=SOURCE_AUTO
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        mins = self.active_seconds // 60
        return f"Session by {self.annotator.username} ({mins}m active)"


class CausalGraph(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_COMPLETE = "complete"
    STATUS_GOLD = "gold"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_COMPLETE, "Complete"),
        (STATUS_GOLD, "Gold"),
    ]

    document = models.ForeignKey(
        "projects.Document", on_delete=models.CASCADE, related_name="graphs"
    )
    annotator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="graphs"
    )
    schema_version = models.ForeignKey(
        "schemas.SchemaVersion", on_delete=models.PROTECT, related_name="graphs"
    )
    ontology_snapshot = models.ForeignKey(
        "ontology.OntologySnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="graphs",
    )
    provenance = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Graph for {self.document.title[:50]} by {self.annotator.username}"


class Node(models.Model):
    ORIGIN_HUMAN = "human"
    ORIGIN_LLM_PROPOSED = "llm_proposed"
    ORIGIN_CHOICES = [
        (ORIGIN_HUMAN, "Human"),
        (ORIGIN_LLM_PROPOSED, "LLM-proposed"),
    ]

    graph = models.ForeignKey(
        CausalGraph, on_delete=models.CASCADE, related_name="nodes"
    )
    node_id = models.CharField(max_length=255, default=_new_uuid)
    name = models.CharField(max_length=500)
    # Promoted for filtering/querying; mirrors data['entity_type']
    category = models.CharField(max_length=50, blank=True)
    data = models.JSONField(default=dict)
    origin = models.CharField(
        max_length=20, choices=ORIGIN_CHOICES, default=ORIGIN_HUMAN
    )
    schema_version = models.ForeignKey(
        "schemas.SchemaVersion", on_delete=models.PROTECT, related_name="nodes"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("graph", "node_id")]
        ordering = ["name"]

    def __str__(self):
        return self.name or self.node_id


class Edge(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_COMPLETE = "complete"
    STATUS_REVIEWED = "reviewed"
    STATUS_GOLD = "gold"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_COMPLETE, "Complete"),
        (STATUS_REVIEWED, "Reviewed"),
        (STATUS_GOLD, "Gold"),
    ]
    ORIGIN_HUMAN = "human"
    ORIGIN_LLM_PROPOSED = "llm_proposed"
    ORIGIN_CHOICES = [
        (ORIGIN_HUMAN, "Human"),
        (ORIGIN_LLM_PROPOSED, "LLM-proposed"),
    ]

    graph = models.ForeignKey(
        CausalGraph, on_delete=models.CASCADE, related_name="edges"
    )
    edge_id = models.CharField(max_length=255, default=_new_uuid)
    subject = models.ForeignKey(
        Node, on_delete=models.PROTECT, related_name="edges_as_subject"
    )
    object = models.ForeignKey(
        Node, on_delete=models.PROTECT, related_name="edges_as_object"
    )
    # Promoted columns for querying/filtering
    predicate = models.CharField(max_length=100, blank=True)
    claim_strength = models.CharField(max_length=50, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )
    origin = models.CharField(
        max_length=20, choices=ORIGIN_CHOICES, default=ORIGIN_HUMAN
    )
    data = models.JSONField(default=dict)
    schema_version = models.ForeignKey(
        "schemas.SchemaVersion", on_delete=models.PROTECT, related_name="edges"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("graph", "edge_id")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} —[{self.predicate}]→ {self.object} [{self.status}]"
