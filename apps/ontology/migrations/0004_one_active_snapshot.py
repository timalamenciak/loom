from django.db import migrations, models


def keep_one_active_snapshot(apps, schema_editor):
    OntologySnapshot = apps.get_model("ontology", "OntologySnapshot")
    active_ids = list(
        OntologySnapshot.objects.filter(is_active=True)
        .order_by("-built_at", "-pk")
        .values_list("pk", flat=True)
    )
    if len(active_ids) > 1:
        OntologySnapshot.objects.filter(pk__in=active_ids[1:]).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("ontology", "0003_load_requests")]

    operations = [
        migrations.RunPython(keep_one_active_snapshot, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="ontologysnapshot",
            constraint=models.UniqueConstraint(
                fields=("is_active",),
                condition=models.Q(is_active=True),
                name="ontology_one_active_snapshot",
            ),
        ),
    ]
