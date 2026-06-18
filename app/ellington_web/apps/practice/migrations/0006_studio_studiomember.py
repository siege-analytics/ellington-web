"""Studios — multi-user practice containers (epic #96 sub-ticket f / #120).

Creates Studio + StudioMember. RecordingShare extension (studio FK) is
a follow-up — landing it standalone keeps this migration small.
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("practice", "0005_recordingcomment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Studio",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                ("slug", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                (
                    "visibility",
                    models.CharField(
                        choices=[
                            ("private", "Private (members only)"),
                            ("link_invite", "Link-invite (anyone with the URL can request to join)"),
                            ("public", "Public (browsable + joinable)"),
                        ],
                        db_index=True,
                        default="private",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        help_text=(
                            "The studio's founder + permanent owner."
                            " PROTECT — owner row outlives the studio's existence."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="studios_owned",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="StudioMember",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("member", "Member"),
                            ("moderator", "Moderator"),
                            ("banned", "Banned"),
                        ],
                        default="member",
                        max_length=16,
                    ),
                ),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                (
                    "invited_by",
                    models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="studio_invites_issued",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "studio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="practice.studio",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        help_text=(
                            "The member. PROTECT — preserve audit trail"
                            " for moderation history."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="studio_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["studio", "user__username"],
            },
        ),
        migrations.AddConstraint(
            model_name="studiomember",
            constraint=models.UniqueConstraint(
                fields=("studio", "user"),
                name="studiomember_studio_user_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="studiomember",
            index=models.Index(
                fields=["user", "studio"],
                name="studiomember_user_idx",
            ),
        ),
    ]
