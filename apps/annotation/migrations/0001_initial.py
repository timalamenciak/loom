import apps.annotation.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("projects", "0001_initial"),
        ("schemas", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CausalGraph",
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
                ("provenance", models.JSONField(default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("complete", "Complete"),
                            ("gold", "Gold"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "annotator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="graphs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="graphs",
                        to="projects.document",
                    ),
                ),
                (
                    "schema_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="graphs",
                        to="schemas.schemaversion",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="WorkSession",
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
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("active_seconds", models.IntegerField(default=0)),
                ("idle_seconds", models.IntegerField(default=0)),
                ("open_seconds", models.IntegerField(default=0)),
                (
                    "source",
                    models.CharField(
                        choices=[("auto", "Auto"), ("manual", "Manual")],
                        default="auto",
                        max_length=10,
                    ),
                ),
                (
                    "annotator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="work_sessions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "assignment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sessions",
                        to="projects.assignment",
                    ),
                ),
            ],
            options={
                "ordering": ["-started_at"],
            },
        ),
        migrations.CreateModel(
            name="Node",
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
                (
                    "node_id",
                    models.CharField(
                        default=apps.annotation.models._new_uuid, max_length=255
                    ),
                ),
                ("name", models.CharField(max_length=500)),
                ("category", models.CharField(blank=True, max_length=50)),
                ("data", models.JSONField(default=dict)),
                (
                    "origin",
                    models.CharField(
                        choices=[
                            ("human", "Human"),
                            ("llm_proposed", "LLM-proposed"),
                        ],
                        default="human",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "graph",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="nodes",
                        to="annotation.causalgraph",
                    ),
                ),
                (
                    "schema_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="nodes",
                        to="schemas.schemaversion",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "unique_together": {("graph", "node_id")},
            },
        ),
        migrations.CreateModel(
            name="Edge",
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
                (
                    "edge_id",
                    models.CharField(
                        default=apps.annotation.models._new_uuid, max_length=255
                    ),
                ),
                ("predicate", models.CharField(blank=True, max_length=100)),
                ("claim_strength", models.CharField(blank=True, max_length=50)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("complete", "Complete"),
                            ("reviewed", "Reviewed"),
                            ("gold", "Gold"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                (
                    "origin",
                    models.CharField(
                        choices=[
                            ("human", "Human"),
                            ("llm_proposed", "LLM-proposed"),
                        ],
                        default="human",
                        max_length=20,
                    ),
                ),
                ("data", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "graph",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="edges",
                        to="annotation.causalgraph",
                    ),
                ),
                (
                    "object",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="edges_as_object",
                        to="annotation.node",
                    ),
                ),
                (
                    "schema_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="edges",
                        to="schemas.schemaversion",
                    ),
                ),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="edges_as_subject",
                        to="annotation.node",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "unique_together": {("graph", "edge_id")},
            },
        ),
    ]
