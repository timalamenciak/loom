import hashlib
from pathlib import Path

import yaml
from django.db import models

_LOOM_UI_YAML_PATH = Path(__file__).resolve().parents[2] / "config" / "loom_ui.yaml"


class SchemaVersion(models.Model):
    version = models.CharField(max_length=50)
    linkml_yaml = models.TextField(help_text="Full LinkML YAML content")
    sha256 = models.CharField(max_length=64)
    is_active = models.BooleanField(default=False)
    loaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-loaded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="schemas_one_active_version",
            )
        ]

    def __str__(self):
        active = " [active]" if self.is_active else ""
        return f"CAMO {self.version}{active}"

    def save(self, *args, **kwargs):
        self.sha256 = hashlib.sha256(self.linkml_yaml.encode()).hexdigest()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "linkml_yaml" in update_fields:
            kwargs["update_fields"] = set(update_fields) | {"sha256"}
        if self.is_active:
            # Only one active schema at a time
            SchemaVersion.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_active(cls):
        return cls.objects.filter(is_active=True).first()


class SchemaUIConfig(models.Model):
    schema_version = models.ForeignKey(
        SchemaVersion,
        on_delete=models.CASCADE,
        related_name="ui_configs",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ui_configs",
    )
    layers = models.JSONField(default=list)
    ontology_routing = models.JSONField(default=dict)
    widget_overrides = models.JSONField(default=dict)
    globally_hidden_slots = models.JSONField(default=list)
    slot_help_text = models.JSONField(default=dict)

    class Meta:
        unique_together = [("schema_version", "project")]

    def __str__(self):
        scope = f"project={self.project_id}" if self.project_id else "schema-level"
        return f"SchemaUIConfig({self.schema_version}, {scope})"

    @classmethod
    def for_schema_version(cls, sv, project=None):
        """Return the most specific SchemaUIConfig for *sv* and *project*.

        Fallback order:
          1. project-level DB record (schema_version=sv, project=project)
          2. schema-level DB record  (schema_version=sv, project=None)
          3. transient instance parsed from config/loom_ui.yaml
        """
        if project is not None:
            record = cls.objects.filter(schema_version=sv, project=project).first()
            if record is not None:
                return record

        schema_record = cls.objects.filter(schema_version=sv, project=None).first()
        if schema_record is not None:
            return schema_record

        raw = yaml.safe_load(_LOOM_UI_YAML_PATH.read_text(encoding="utf-8")) or {}
        return cls(
            schema_version=sv,
            project=None,
            layers=raw.get("layers") or [],
            ontology_routing=raw.get("ontology_routing") or {},
            widget_overrides=raw.get("widget_overrides") or {},
            globally_hidden_slots=raw.get("globally_hidden_slots") or [],
            slot_help_text=raw.get("slot_help_text") or {},
        )
