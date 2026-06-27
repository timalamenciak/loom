import hashlib

import django.db.models.deletion
from django.db import migrations, models


def migrate_legacy_snapshots(apps, schema_editor):
    Snapshot = apps.get_model("ontology", "OntologySnapshot")
    Release = apps.get_model("ontology", "OntologyRelease")
    Term = apps.get_model("ontology", "OntologyTerm")

    for snapshot in Snapshot.objects.all().iterator():
        pairs = []
        prefixes = (
            Term.objects.filter(snapshot=snapshot)
            .values_list("prefix", flat=True)
            .distinct()
        )
        for prefix in prefixes:
            meta = (snapshot.source_versions or {}).get(prefix, {})
            release = Release.objects.create(
                name=meta.get("name", prefix.lower()),
                prefix=prefix,
                source_url=meta.get("url", "legacy-snapshot"),
                source_sha256="",
                term_count=Term.objects.filter(
                    snapshot=snapshot, prefix=prefix
                ).count(),
                status="ready",
            )
            Term.objects.filter(snapshot=snapshot, prefix=prefix).update(
                release=release
            )
            snapshot.releases.add(release)
            pairs.append(f"{prefix}:legacy-{release.pk}")
        snapshot.manifest_sha256 = hashlib.sha256(
            "\n".join(sorted(pairs)).encode()
        ).hexdigest()
        snapshot.save(update_fields=["manifest_sha256"])


class Migration(migrations.Migration):
    dependencies = [("ontology", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="OntologyRelease",
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
                ("prefix", models.CharField(db_index=True, max_length=50)),
                ("source_url", models.TextField()),
                (
                    "source_sha256",
                    models.CharField(blank=True, db_index=True, max_length=64),
                ),
                ("loaded_at", models.DateTimeField(auto_now_add=True)),
                ("term_count", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("loading", "Loading"),
                            ("ready", "Ready"),
                            ("failed", "Failed"),
                        ],
                        default="loading",
                        max_length=20,
                    ),
                ),
                ("error", models.TextField(blank=True)),
            ],
            options={"ordering": ["prefix", "-loaded_at"]},
        ),
        migrations.AddField(
            model_name="ontologysnapshot",
            name="manifest_sha256",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="ontologysnapshot",
            name="releases",
            field=models.ManyToManyField(
                blank=True, related_name="snapshots", to="ontology.ontologyrelease"
            ),
        ),
        migrations.AddField(
            model_name="ontologyterm",
            name="release",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="terms",
                to="ontology.ontologyrelease",
            ),
        ),
        migrations.AlterField(
            model_name="ontologyterm",
            name="snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="terms",
                to="ontology.ontologysnapshot",
            ),
        ),
        migrations.AlterUniqueTogether(name="ontologyterm", unique_together=set()),
        migrations.AddConstraint(
            model_name="ontologyterm",
            constraint=models.UniqueConstraint(
                condition=models.Q(("snapshot__isnull", False)),
                fields=("snapshot", "curie"),
                name="unique_legacy_snapshot_curie",
            ),
        ),
        migrations.AddConstraint(
            model_name="ontologyterm",
            constraint=models.UniqueConstraint(
                condition=models.Q(("release__isnull", False)),
                fields=("release", "curie"),
                name="unique_release_curie",
            ),
        ),
        migrations.AddIndex(
            model_name="ontologyterm",
            index=models.Index(
                fields=["release", "prefix"], name="ontology_release_prefix_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="ontologyterm",
            index=models.Index(
                fields=["release", "curie"], name="ontology_release_curie_idx"
            ),
        ),
        migrations.RunPython(migrate_legacy_snapshots, migrations.RunPython.noop),
    ]
