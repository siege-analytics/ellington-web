"""Follow model — one-way relationships (epic #96 sub-ticket h / #122)."""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_account_deletion_audit_self_delete"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Follow",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "follower",
                    models.ForeignKey(
                        help_text="The user doing the following.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="following",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "followed",
                    models.ForeignKey(
                        help_text="The user being followed.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="followers",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="follow",
            constraint=models.UniqueConstraint(
                fields=("follower", "followed"),
                name="follow_follower_followed_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="follow",
            constraint=models.CheckConstraint(
                condition=models.Q(("follower", models.F("followed")), _negated=True),
                name="follow_no_self_follow",
            ),
        ),
        migrations.AddIndex(
            model_name="follow",
            index=models.Index(
                fields=["followed", "-created_at"],
                name="follow_followed_recent_idx",
            ),
        ),
    ]
