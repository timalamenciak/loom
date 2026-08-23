import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0001_initial"),
        ("schemas", "0002_one_active_schema"),
    ]

    operations = [
        migrations.CreateModel(
            name="SchemaUIConfig",
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
                    "schema_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ui_configs",
                        to="schemas.schemaversion",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ui_configs",
                        to="projects.project",
                    ),
                ),
                ("layers", models.JSONField(default=list)),
                ("ontology_routing", models.JSONField(default=dict)),
                ("widget_overrides", models.JSONField(default=dict)),
                ("globally_hidden_slots", models.JSONField(default=list)),
                ("slot_help_text", models.JSONField(default=dict)),
            ],
            options={
                "unique_together": {("schema_version", "project")},
            },
        ),
    ]
