import django.db.models.deletion
from django.db import migrations, models


def backfill_graph_snapshots(apps, schema_editor):
    Graph = apps.get_model("annotation", "CausalGraph")
    for graph in Graph.objects.select_related("document__project").iterator():
        graph.ontology_snapshot_id = graph.document.project.ontology_snapshot_id
        graph.save(update_fields=["ontology_snapshot"])


class Migration(migrations.Migration):
    dependencies = [
        ("annotation", "0001_initial"),
        ("ontology", "0002_releases"),
        ("projects", "0003_project_configuration"),
    ]

    operations = [
        migrations.AddField(
            model_name="causalgraph",
            name="ontology_snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="graphs",
                to="ontology.ontologysnapshot",
            ),
        ),
        migrations.RunPython(backfill_graph_snapshots, migrations.RunPython.noop),
    ]
