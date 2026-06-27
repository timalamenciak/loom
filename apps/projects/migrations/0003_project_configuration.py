import django.db.models.deletion
from django.db import migrations, models


def backfill_configuration(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    SchemaVersion = apps.get_model("schemas", "SchemaVersion")
    Snapshot = apps.get_model("ontology", "OntologySnapshot")
    schema = SchemaVersion.objects.filter(is_active=True).first()
    snapshot = Snapshot.objects.filter(is_active=True).first()
    names = []
    if snapshot:
        names = sorted(
            meta.get("name", prefix.lower())
            for prefix, meta in (snapshot.source_versions or {}).items()
        )
    Project.objects.update(
        active_schema=schema,
        ontology_snapshot=snapshot,
        ontology_names=names,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ontology", "0002_releases"),
        ("projects", "0002_assignment_graph"),
        ("schemas", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="active_schema",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="projects",
                to="schemas.schemaversion",
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="auto_infer_ontologies",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="project",
            name="ontology_names",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="project",
            name="ontology_snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="projects",
                to="ontology.ontologysnapshot",
            ),
        ),
        migrations.RunPython(backfill_configuration, migrations.RunPython.noop),
    ]
