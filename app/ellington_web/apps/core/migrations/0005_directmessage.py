"""DirectMessage — 1:1 messages (epic #96 sub-ticket g / #124)."""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_follow"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DirectMessage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                ("body", models.TextField()),
                ("sent_at", models.DateTimeField(auto_now_add=True)),
                (
                    "read_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "sender",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dms_sent",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dms_received",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["sent_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="directmessage",
            constraint=models.CheckConstraint(
                condition=models.Q(("sender", models.F("recipient")), _negated=True),
                name="dm_no_self_send",
            ),
        ),
        migrations.AddIndex(
            model_name="directmessage",
            index=models.Index(
                fields=["sender", "recipient", "sent_at"],
                name="dm_pair_chrono_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="directmessage",
            index=models.Index(
                fields=["recipient", "read_at"],
                name="dm_recipient_unread_idx",
            ),
        ),
    ]
