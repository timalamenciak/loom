from django.db import migrations, models


def repair_sessions(apps, schema_editor):
    WorkSession = apps.get_model("annotation", "WorkSession")
    for field_name in ("active_seconds", "idle_seconds", "open_seconds"):
        WorkSession.objects.filter(**{f"{field_name}__lt": 0}).update(
            **{field_name: 0}
        )

    groups = (
        WorkSession.objects.filter(ended_at__isnull=True)
        .values("assignment_id", "annotator_id")
        .annotate(count=models.Count("pk"))
        .filter(count__gt=1)
    )
    for group in groups:
        sessions = WorkSession.objects.filter(
            assignment_id=group["assignment_id"],
            annotator_id=group["annotator_id"],
            ended_at__isnull=True,
        ).order_by("-started_at", "-pk")
        for session in sessions[1:]:
            session.ended_at = session.started_at
            session.open_seconds = 0
            session.save(update_fields=["ended_at", "open_seconds"])


class Migration(migrations.Migration):
    dependencies = [("annotation", "0002_graph_ontology_snapshot")]

    operations = [
        migrations.RunPython(repair_sessions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="worksession",
            name="active_seconds",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="worksession",
            name="idle_seconds",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="worksession",
            name="open_seconds",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddConstraint(
            model_name="worksession",
            constraint=models.UniqueConstraint(
                fields=("assignment", "annotator"),
                condition=models.Q(ended_at__isnull=True),
                name="annotation_one_open_session",
            ),
        ),
    ]
