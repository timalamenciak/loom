from django import forms
from django.urls import reverse

from .models import ProposerConfig

# The LLM seam's model choice is an operational/deployment setting, not a CAMO
# schema slot — restricting it here doesn't violate "schema-driven" (see
# CLAUDE.md's "one defining constraint", which is scoped to annotation fields).
MODEL_CHOICES = [
    ("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
    ("claude-sonnet-5", "Claude Sonnet 5"),
    ("claude-opus-4-8", "Claude Opus 4.8"),
]


class ProposerConfigForm(forms.ModelForm):
    model = forms.ChoiceField(choices=MODEL_CHOICES)

    class Meta:
        model = ProposerConfig
        fields = [
            "is_enabled",
            "model",
            "api_key_env_var",
            "trigger",
            "max_proposals_per_document",
            "max_shots",
        ]
        widgets = {
            "max_proposals_per_document": forms.NumberInput(attrs={"min": 1}),
            "max_shots": forms.NumberInput(attrs={"min": 0}),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project is not None:
            self.fields["api_key_env_var"].widget.attrs.update(
                {
                    "hx-post": reverse("llm-config-check-env-var", args=[project.pk]),
                    "hx-trigger": "keyup changed delay:500ms, load",
                    "hx-target": "#env-var-status",
                    "hx-swap": "innerHTML",
                }
            )
