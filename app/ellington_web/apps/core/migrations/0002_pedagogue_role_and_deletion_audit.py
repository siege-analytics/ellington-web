"""Add Pedagogue side-role + account-deletion audit (epic #96 sub-ticket a, #100).

- UserProfile.is_pedagogue boolean (db_index=True; #98 will filter on it)
- AccountDeletionAudit model — populated by delete_user_account command

Sentinel "deleted-user" auth.User row is created lazily by
``apps.core.models.get_or_create_deleted_user_sentinel()`` rather than
seeded in a data migration, so the username is editable later without
a schema change.
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="is_pedagogue",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "Stackable role: submit engine-rule confirmations,"
                    " comment on charts/voicings, author Master commentary."
                    " Set by admin via Grappelli (gated in UserProfileAdmin)."
                ),
            ),
        ),
        migrations.CreateModel(
            name="AccountDeletionAudit",
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
                (
                    "deleted_username",
                    models.CharField(
                        help_text=(
                            "Denormalized — auth.User row is gone by the"
                            " time this is written."
                        ),
                        max_length=150,
                    ),
                ),
                ("deleted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "anonymized_artifact_counts",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            "Per-artifact counts: how many Comments/Responses"
                            " were repointed to the sentinel, how many"
                            " Goals/Recordings were hard-deleted. Shape:"
                            " {'goals_deleted': N, 'recordings_deleted': N,"
                            " 'comments_anonymized': N, ...}"
                        ),
                    ),
                ),
                (
                    "deleted_by",
                    models.ForeignKey(
                        help_text="Admin who initiated the deletion.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="account_deletions_initiated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-deleted_at"],
            },
        ),
    ]
