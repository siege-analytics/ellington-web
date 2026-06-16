"""Add ``PracticeSession.tempo_bpm`` — per-session tempo override.

Phase 2 of the practice-feedback loop epic (#60). The form collected
``tempo_bpm`` from day one but didn't persist it; this migration adds
the missing column so the value survives form save → DB. Backfill-safe:
existing rows get NULL, which means "fall back to song default."
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("practice", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="practicesession",
            name="tempo_bpm",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
