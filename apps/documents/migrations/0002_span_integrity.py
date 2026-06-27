from django.db import migrations, models


def repair_span_offsets(apps, schema_editor):
    TextSpan = apps.get_model("documents", "TextSpan")
    invalid = TextSpan.objects.filter(
        models.Q(start_char__lt=0) | models.Q(end_char__lte=models.F("start_char"))
    )
    for span in invalid.iterator():
        span.start_char = max(0, span.start_char)
        span.end_char = max(span.start_char + 1, span.end_char)
        span.save(update_fields=["start_char", "end_char"])


class Migration(migrations.Migration):
    dependencies = [("documents", "0001_initial")]

    operations = [
        migrations.RunPython(repair_span_offsets, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="textspan",
            constraint=models.CheckConstraint(
                condition=models.Q(start_char__gte=0),
                name="documents_span_start_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="textspan",
            constraint=models.CheckConstraint(
                condition=models.Q(end_char__gt=models.F("start_char")),
                name="documents_span_end_after_start",
            ),
        ),
    ]
