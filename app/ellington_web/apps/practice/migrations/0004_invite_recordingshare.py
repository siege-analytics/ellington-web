"""Recording sharing + invite-a-friend (epic #96 sub-ticket b / #108).

Creates the Invite + RecordingShare tables. No data migration —
existing Recordings remain owner-only until someone shares them.
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("practice", "0003_recording_analysis_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Invite",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                (
                    "token",
                    models.CharField(
                        db_index=True,
                        help_text="URL-safe random token. 256-bit entropy.",
                        max_length=64,
                        unique=True,
                    ),
                ),
                ("email", models.EmailField(max_length=254)),
                ("name_hint", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "expires_at",
                    models.DateTimeField(
                        help_text=(
                            "Token expiry. Default 30 days from creation;"
                            " set by the form layer."
                        ),
                    ),
                ),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "inviter",
                    models.ForeignKey(
                        help_text=(
                            "Who sent the invite. PROTECT so audit history"
                            " survives user deletion via the sentinel-user repoint."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="invites_sent",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "redeemed_by",
                    models.ForeignKey(
                        blank=True, null=True,
                        help_text=(
                            "The User row created when the invite was accepted."
                            " Null until then."
                        ),
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="invites_redeemed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="invite",
            index=models.Index(
                fields=["email", "-created_at"],
                name="invite_email_recent_idx",
            ),
        ),
        migrations.CreateModel(
            name="RecordingShare",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                ("share_note", models.TextField(blank=True)),
                ("shared_at", models.DateTimeField(auto_now_add=True)),
                (
                    "recording",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shares",
                        to="practice.recording",
                    ),
                ),
                (
                    "sharer",
                    models.ForeignKey(
                        help_text="Who initiated the share. PROTECT — audit trail.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="recording_shares_sent",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "recipient",
                    models.ForeignKey(
                        blank=True, null=True,
                        help_text=(
                            "The User who can see the Recording. Null until"
                            " an anchored Invite is redeemed; backfilled then."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="recording_shares_received",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "invite",
                    models.ForeignKey(
                        blank=True, null=True,
                        help_text=(
                            "The Invite this share is waiting on. Null once"
                            " the invitee has signed up."
                        ),
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="anchored_shares",
                        to="practice.invite",
                    ),
                ),
            ],
            options={
                "ordering": ["-shared_at"],
            },
        ),
        migrations.AddIndex(
            model_name="recordingshare",
            index=models.Index(
                fields=["recipient", "-shared_at"],
                name="recshare_recipient_recent_idx",
            ),
        ),
    ]
