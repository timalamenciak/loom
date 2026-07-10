from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("documents", "0002_span_integrity")]

    operations = [
        migrations.AddField(
            model_name="textspan",
            name="text_source",
            field=models.CharField(default="canonical_text", max_length=20),
        ),
    ]
