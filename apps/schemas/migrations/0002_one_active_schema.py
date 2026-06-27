from django.db import migrations, models


def keep_one_active_schema(apps, schema_editor):
    SchemaVersion = apps.get_model("schemas", "SchemaVersion")
    active_ids = list(
        SchemaVersion.objects.filter(is_active=True)
        .order_by("-loaded_at", "-pk")
        .values_list("pk", flat=True)
    )
    if len(active_ids) > 1:
        SchemaVersion.objects.filter(pk__in=active_ids[1:]).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("schemas", "0001_initial")]

    operations = [
        migrations.RunPython(keep_one_active_schema, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="schemaversion",
            constraint=models.UniqueConstraint(
                fields=("is_active",),
                condition=models.Q(is_active=True),
                name="schemas_one_active_version",
            ),
        ),
    ]
