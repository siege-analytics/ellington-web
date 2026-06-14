"""Add Recording.analysis_status + analysis_task_id + analysis_completed_at.

Phase 3a (#67) of the practice-feedback loop epic (#60). Adds the
lifecycle state field for sub-4 audio analysis. New rows default to
``PENDING``; existing rows (none at the time this migration was
authored — Phase 1 + 1b + 2 haven't shipped uploads to prod yet) also
default to ``PENDING``.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("practice", "0002_practicesession_tempo_bpm"),
    ]

    operations = [
        migrations.AddField(
            model_name="recording",
            name="analysis_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("complete", "Complete"),
                    ("failed", "Failed"),
                ],
                default="pending",
                db_index=True,
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="recording",
            name="analysis_task_id",
            field=models.CharField(
                blank=True,
                help_text="Celery task ID of the most-recent analyze_recording dispatch.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="recording",
            name="analysis_completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
