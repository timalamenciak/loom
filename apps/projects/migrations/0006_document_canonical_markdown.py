from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0005_project_hidden_slots")]

    operations = [
        migrations.AddField(
            model_name="document",
            name="canonical_markdown",
            field=models.TextField(blank=True, null=True),
        ),
    ]
