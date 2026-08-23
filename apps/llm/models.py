import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ProposerConfig(models.Model):
    TRIGGER_MANUAL = "manual"
    TRIGGER_ON_ASSIGNMENT = "on_assignment"
    TRIGGER_CHOICES = [
        (TRIGGER_MANUAL, "Manual"),
        (TRIGGER_ON_ASSIGNMENT, "On Assignment"),
    ]

    project = models.OneToOneField(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="llm_config",
    )
    is_enabled = models.BooleanField(default=False)
    model = models.CharField(max_length=100, default="claude-sonnet-5")
    max_tokens = models.IntegerField(default=4096)
    api_key_env_var = models.CharField(
        max_length=100,
        blank=True,
        help_text="Name of the environment variable holding the API key — never the key itself.",
    )
    trigger = models.CharField(
        max_length=20, choices=TRIGGER_CHOICES, default=TRIGGER_MANUAL
    )
    max_proposals_per_document = models.IntegerField(default=20)
    max_shots = models.IntegerField(default=5)

    def __str__(self):
        return f"ProposerConfig({self.project_id}, enabled={self.is_enabled})"

    def clean(self):
        if self.is_enabled and not self.api_key_env_var:
            raise ValidationError({"api_key_env_var": "Required when LLM is enabled."})
        if self.is_enabled and not os.environ.get(self.api_key_env_var):
            raise ValidationError(
                {"api_key_env_var": f"Env var {self.api_key_env_var!r} is not set."}
            )


class FewShotExample(models.Model):
    """A human-approved edge selected as a few-shot example for this project's
    proposal prompts — only 'complete' or 'gold' edges qualify, since a shot
    the model imitates must itself be something a human has signed off on.
    """

    ELIGIBLE_EDGE_STATUSES = ("complete", "gold")

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="few_shot_examples",
    )
    edge = models.ForeignKey(
        "annotation.Edge",
        on_delete=models.CASCADE,
        related_name="few_shot_examples",
    )
    label = models.CharField(max_length=200, blank=True)
    selected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="selected_few_shot_examples",
    )
    selected_at = models.DateTimeField(auto_now_add=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = [("project", "edge")]
        ordering = ["display_order", "selected_at"]

    def __str__(self):
        return self.label or f"FewShotExample(edge={self.edge_id})"

    def clean(self):
        if self.edge.status not in self.ELIGIBLE_EDGE_STATUSES:
            raise ValidationError(
                {
                    "edge": "Only complete or gold edges can be used as "
                    "few-shot examples."
                }
            )


class ProposalOutcome(models.Model):
    """What happened to one LLM-proposed edge — the acceptance-rate and
    edit-distance metrics the review queue's accept/reject actions feed.

    edge is SET_NULL rather than CASCADE on purpose: Reject hard-deletes the
    Edge (see apps.llm.views.ProposalRejectView), and a metrics row that
    vanished the instant it was written would make rejection-rate impossible
    to compute — the outcome must outlive the edge it was measured on. project
    and document are denormalized for the same reason: once edge is nulled by
    a rejection, `edge__graph__document__project` can no longer resolve, but
    the metrics dashboard (apps.llm.views.LLMMetricsView) still needs to
    group every outcome — accepted, rejected, or pending — by project and by
    document.
    """

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="proposal_outcomes",
    )
    document = models.ForeignKey(
        "projects.Document",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="proposal_outcomes",
    )
    edge = models.OneToOneField(
        "annotation.Edge",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposal_outcome",
    )
    proposed_data = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Snapshot of the edge's data as first proposed by the LLM, before "
            "any human edit — the baseline edit_distance is measured against."
        ),
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    edit_distance = models.IntegerField(null=True, blank=True)
    time_to_review_seconds = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"ProposalOutcome(edge={self.edge_id})"
