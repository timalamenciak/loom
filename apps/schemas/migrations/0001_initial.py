from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SchemaVersion",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("version", models.CharField(max_length=50)),
                (
                    "linkml_yaml",
                    models.TextField(help_text="Full LinkML YAML content"),
                ),
                ("sha256", models.CharField(max_length=64)),
                ("is_active", models.BooleanField(default=False)),
                ("loaded_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-loaded_at"],
            },
        ),
    ]
