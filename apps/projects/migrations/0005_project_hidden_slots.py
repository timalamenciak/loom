from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0004_project_rollup")]

    operations = [
        migrations.AddField(
            model_name="project",
            name="hidden_slots",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
