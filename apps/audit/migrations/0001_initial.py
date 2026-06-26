import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("ts", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("action", models.CharField(db_index=True, max_length=50)),
                ("target_type", models.CharField(max_length=50)),
                ("target_id", models.CharField(blank=True, max_length=100)),
                ("diff", models.JSONField(default=dict)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-ts"],
                "indexes": [
                    models.Index(
                        fields=["actor", "ts"], name="audit_audit_actor_i_0b33df_idx"
                    ),
                    models.Index(
                        fields=["action", "ts"], name="audit_audit_action__f7a99b_idx"
                    ),
                ],
            },
        ),
    ]
