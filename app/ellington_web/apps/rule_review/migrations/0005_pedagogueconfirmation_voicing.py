"""Add optional voicing FK to PedagogueConfirmation (#286).

Records which candidate voicing the pedagogue was looking at when
they confirmed. SET_NULL on voicing delete — corpus rotation must
not orphan confirmation rows. Nullable and blank because the pin
is only needed when the resolver returns >1 candidate.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rule_review", "0004_alter_pedagogueconfirmation_id"),
        ("voicings", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="pedagogueconfirmation",
            name="voicing",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="voicings.voicing",
                help_text=(
                    "Which candidate voicing this confirmation is "
                    "pinned to. Nullable — no pin required when "
                    "candidates == 0 or 1."
                ),
            ),
        ),
    ]
