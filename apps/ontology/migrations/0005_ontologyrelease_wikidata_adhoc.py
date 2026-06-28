import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ontology", "0004_one_active_snapshot"),
        ("projects", "0003_project_configuration"),
    ]

    operations = [
        migrations.AddField(
            model_name="ontologyrelease",
            name="source_kind",
            field=models.CharField(
                choices=[
                    ("bulk", "Bulk OBO/OWL load"),
                    ("wikidata_adhoc", "Ad hoc Wikidata picks"),
                ],
                db_index=True,
                default="bulk",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="ontologyrelease",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="wikidata_adhoc_releases",
                to="projects.project",
            ),
        ),
        migrations.AddConstraint(
            model_name="ontologyrelease",
            constraint=models.UniqueConstraint(
                condition=models.Q(source_kind="wikidata_adhoc"),
                fields=["project", "prefix"],
                name="unique_wikidata_adhoc_per_project_prefix",
            ),
        ),
    ]
