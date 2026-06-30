"""Align PedagogueConfirmation.id with apps.rule_review's
``default_auto_field = BigAutoField`` (set in apps.py). Migration 0003
was generated when the field defaulted to ``AutoField``; Django's
``makemigrations --check`` flags the divergence even though no rows
exist yet. Per #186 Phase 1.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rule_review", "0003_pedagogueconfirmation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pedagogueconfirmation",
            name="id",
            field=models.BigAutoField(
                auto_created=True,
                primary_key=True,
                serialize=False,
                verbose_name="ID",
            ),
        ),
    ]
