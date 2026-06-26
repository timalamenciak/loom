from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="OntologySnapshot",
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
                ("name", models.CharField(max_length=200)),
                ("built_at", models.DateTimeField(auto_now_add=True)),
                ("source_versions", models.JSONField(default=dict)),
                ("is_active", models.BooleanField(default=False)),
            ],
            options={
                "ordering": ["-built_at"],
            },
        ),
        migrations.CreateModel(
            name="OntologyTerm",
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
                ("prefix", models.CharField(db_index=True, max_length=50)),
                ("curie", models.CharField(max_length=200)),
                ("label", models.CharField(max_length=1000)),
                ("synonyms", models.JSONField(blank=True, default=list)),
                ("synonym_labels", models.TextField(blank=True)),
                ("definition", models.TextField(blank=True)),
                ("obsolete", models.BooleanField(db_index=True, default=False)),
                (
                    "snapshot",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="terms",
                        to="ontology.ontologysnapshot",
                    ),
                ),
            ],
            options={
                "unique_together": {("snapshot", "curie")},
                "indexes": [
                    models.Index(
                        fields=["snapshot", "prefix"],
                        name="ontology_on_snapsho_1680f5_idx",
                    ),
                    models.Index(
                        fields=["snapshot", "curie"],
                        name="ontology_on_snapsho_258343_idx",
                    ),
                ],
            },
        ),
    ]
