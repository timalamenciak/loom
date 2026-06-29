from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0003_project_configuration")]

    operations = [
        migrations.AddField(
            model_name="project",
            name="source_document_rollup",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
