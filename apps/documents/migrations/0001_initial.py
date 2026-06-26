import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("annotation", "0001_initial"),
        ("projects", "0002_assignment_graph"),
    ]

    operations = [
        migrations.CreateModel(
            name="TextSpan",
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
                ("start_char", models.IntegerField()),
                ("end_char", models.IntegerField()),
                ("text", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_spans",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="spans",
                        to="projects.document",
                    ),
                ),
                (
                    "edge",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="spans",
                        to="annotation.edge",
                    ),
                ),
                (
                    "node",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="spans",
                        to="annotation.node",
                    ),
                ),
            ],
            options={
                "ordering": ["start_char"],
                "indexes": [
                    models.Index(
                        fields=["document", "start_char", "end_char"],
                        name="documents_t_documen_7414e6_idx",
                    ),
                ],
            },
        ),
    ]
