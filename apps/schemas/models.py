import hashlib

from django.db import models


class SchemaVersion(models.Model):
    version = models.CharField(max_length=50)
    linkml_yaml = models.TextField(help_text="Full LinkML YAML content")
    sha256 = models.CharField(max_length=64)
    is_active = models.BooleanField(default=False)
    loaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-loaded_at"]

    def __str__(self):
        active = " [active]" if self.is_active else ""
        return f"CAMO {self.version}{active}"

    def save(self, *args, **kwargs):
        self.sha256 = hashlib.sha256(self.linkml_yaml.encode()).hexdigest()
        if self.is_active:
            # Only one active schema at a time
            SchemaVersion.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_active(cls):
        return cls.objects.filter(is_active=True).first()
