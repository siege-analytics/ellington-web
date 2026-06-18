"""Comments on Recordings (epic #96 sub-ticket d / #110).

Creates the RecordingComment table. Soft-delete via ``deleted_at``;
no rows are ever removed automatically.
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("practice", "0004_invite_recordingshare"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RecordingComment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                ("body", models.TextField()),
                (
                    "anchor_ms",
                    models.PositiveIntegerField(
                        blank=True, null=True,
                        help_text=(
                            "Time offset in the recording, in milliseconds."
                            " Null = whole-recording comment."
                        ),
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "edited_at",
                    models.DateTimeField(
                        blank=True, null=True,
                        help_text="Set on author's first edit; sticky after that.",
                    ),
                ),
                (
                    "deleted_at",
                    models.DateTimeField(
                        blank=True, db_index=True, null=True,
                        help_text=(
                            "Soft-delete marker. Body redacted to '[deleted]'"
                            " while preserving thread shape."
                        ),
                    ),
                ),
                (
                    "author",
                    models.ForeignKey(
                        help_text=(
                            "Comment author. PROTECT — sentinel-anonymize on"
                            " user delete."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="recording_comments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True, null=True,
                        help_text="Parent comment for threading. Null = top-level.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="replies",
                        to="practice.recordingcomment",
                    ),
                ),
                (
                    "recording",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="practice.recording",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="recordingcomment",
            index=models.Index(
                fields=["recording", "created_at"],
                name="reccomment_rec_chrono_idx",
            ),
        ),
    ]
