from django.conf import settings
from django.db import models


class TextSpan(models.Model):
    document = models.ForeignKey(
        "projects.Document",
        on_delete=models.CASCADE,
        related_name="spans",
    )
    start_char = models.IntegerField()
    end_char = models.IntegerField()
    text = models.TextField(blank=True)
    text_source = models.CharField(max_length=20, default="canonical_text")
    node = models.ForeignKey(
        "annotation.Node",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="spans",
    )
    edge = models.ForeignKey(
        "annotation.Edge",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="spans",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_spans",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_char"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_char__gte=0),
                name="documents_span_start_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(end_char__gt=models.F("start_char")),
                name="documents_span_end_after_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=["document", "start_char", "end_char"],
                name="documents_t_documen_7414e6_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.start_char}:{self.end_char}] {self.text[:40]!r}"
