import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("annotation", "0001_initial"),
        ("projects", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="assignment",
            name="graph",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assignments",
                to="annotation.causalgraph",
            ),
        ),
    ]
