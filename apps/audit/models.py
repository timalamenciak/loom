from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    ts = models.DateTimeField(auto_now_add=True, db_index=True)
    action = models.CharField(max_length=50, db_index=True)
    target_type = models.CharField(max_length=50)
    target_id = models.CharField(max_length=100, blank=True)
    diff = models.JSONField(default=dict)

    class Meta:
        ordering = ["-ts"]
        indexes = [
            models.Index(fields=["actor", "ts"], name="audit_audit_actor_i_0b33df_idx"),
            models.Index(
                fields=["action", "ts"], name="audit_audit_action__f7a99b_idx"
            ),
        ]

    def __str__(self):
        return (
            f"{self.actor.username} {self.action} {self.target_type}#{self.target_id}"
        )
