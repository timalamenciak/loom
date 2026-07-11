import os

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

    def __str__(self):
        return f"ProposerConfig({self.project_id}, enabled={self.is_enabled})"

    def clean(self):
        if self.is_enabled and not self.api_key_env_var:
            raise ValidationError({"api_key_env_var": "Required when LLM is enabled."})
        if self.is_enabled and not os.environ.get(self.api_key_env_var):
            raise ValidationError(
                {"api_key_env_var": f"Env var {self.api_key_env_var!r} is not set."}
            )
