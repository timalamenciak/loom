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
            name="Project",
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
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="owned_projects",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Document",
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
                    "source",
                    models.CharField(
                        choices=[
                            ("pdf_upload", "PDF Upload"),
                            ("ris_import", "RIS Import"),
                            ("manual", "Manual"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "pdf_file",
                    models.FileField(blank=True, null=True, upload_to="pdfs/"),
                ),
                ("sha256", models.CharField(blank=True, max_length=64, null=True)),
                ("canonical_text", models.TextField(blank=True, null=True)),
                ("page_map", models.JSONField(blank=True, null=True)),
                ("title", models.TextField()),
                ("authors", models.JSONField(default=list)),
                ("year", models.IntegerField(blank=True, null=True)),
                (
                    "doi",
                    models.CharField(
                        blank=True, db_index=True, max_length=512, null=True
                    ),
                ),
                ("journal", models.CharField(blank=True, max_length=512)),
                ("abstract", models.TextField(blank=True)),
                ("ris_raw", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "ordering": ["title"],
            },
        ),
        migrations.CreateModel(
            name="Assignment",
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
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("assigned", "Assigned"),
                            ("in_progress", "In progress"),
                            ("submitted", "Submitted"),
                            ("reviewed", "Reviewed"),
                            ("returned", "Returned"),
                        ],
                        default="assigned",
                        max_length=20,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "annotator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "assigned_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assignments_given",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignments",
                        to="projects.document",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignments",
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "ordering": ["-assigned_at"],
                "unique_together": {("document", "annotator")},
            },
        ),
        migrations.CreateModel(
            name="ProjectMembership",
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
                    "role",
                    models.CharField(
                        choices=[
                            ("admin", "Admin"),
                            ("reviewer", "Reviewer"),
                            ("annotator", "Annotator"),
                        ],
                        default="annotator",
                        max_length=20,
                    ),
                ),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="projects.project",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["role", "user__username"],
                "unique_together": {("project", "user")},
            },
        ),
        migrations.AddConstraint(
            model_name="document",
            constraint=models.UniqueConstraint(
                condition=(
                    models.Q(("doi__isnull", False))
                    & ~models.Q(("doi", ""))
                ),
                fields=("project", "doi"),
                name="unique_document_doi_per_project",
            ),
        ),
    ]
