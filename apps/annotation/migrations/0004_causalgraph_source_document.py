from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("annotation", "0003_session_integrity"),
    ]

    operations = [
        migrations.AddField(
            model_name="causalgraph",
            name="source_document",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
