import django.db.models.deletion
from django.db import migrations, models


def seed_existing_requests(apps, schema_editor):
    LoadRequest = apps.get_model("ontology", "OntologyLoadRequest")
    LoadItem = apps.get_model("ontology", "OntologyLoadItem")
    for request in LoadRequest.objects.all().iterator():
        for name in request.ontology_names or []:
            LoadItem.objects.get_or_create(
                request=request,
                name=name,
                defaults={
                    "prefix": name,
                    "status": request.status,
                    "error": request.error,
                    "started_at": request.started_at,
                    "finished_at": request.finished_at,
                },
            )


class Migration(migrations.Migration):
    dependencies = [("ontology", "0006_adhocontologysource")]

    operations = [
        migrations.CreateModel(
            name="OntologyLoadItem",
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
                ("name", models.CharField(max_length=200)),
                ("prefix", models.CharField(max_length=50)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("complete", "Complete"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("term_count", models.PositiveIntegerField(default=0)),
                ("error", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="ontology.ontologyloadrequest",
                    ),
                ),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="ontologyloaditem",
            constraint=models.UniqueConstraint(
                fields=("request", "name"), name="unique_ontology_load_item"
            ),
        ),
        migrations.RunPython(seed_existing_requests, migrations.RunPython.noop),
    ]
