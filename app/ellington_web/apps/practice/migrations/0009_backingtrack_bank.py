"""Add ``bank`` FK on ``BackingTrack`` → ``audio.SoundBank`` (#233).

PROTECT — deleting a bank should not orphan rendered backings.
Nullable for backfill compatibility with existing rows.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("practice", "0008_alter_invite_email_alter_invite_expires_at_and_more"),
        ("audio", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="backingtrack",
            name="bank",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="backing_tracks",
                to="audio.soundbank",
                help_text=(
                    "Which SoundBank rendered this backing's audio. "
                    "Nullable for back-compat with backings ingested "
                    "before #233 landed."
                ),
            ),
        ),
    ]
