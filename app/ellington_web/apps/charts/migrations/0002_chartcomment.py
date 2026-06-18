"""Chart comments (epic #96 sub-ticket e / #114).

Creates the ChartComment table with one-of (song/section/chord_event)
anchor enforced by a CheckConstraint.
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("charts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChartComment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                ("body", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("edited_at", models.DateTimeField(blank=True, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                (
                    "author",
                    models.ForeignKey(
                        help_text=(
                            "Comment author. PROTECT — sentinel-anonymize"
                            " on user delete."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="chart_comments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "song",
                    models.ForeignKey(
                        blank=True, null=True,
                        help_text=(
                            "Anchor: whole-song comment. Exactly one"
                            " anchor must be set."
                        ),
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="charts.song",
                    ),
                ),
                (
                    "section",
                    models.ForeignKey(
                        blank=True, null=True,
                        help_text="Anchor: per-section / per-form comment.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="charts.section",
                    ),
                ),
                (
                    "chord_event",
                    models.ForeignKey(
                        blank=True, null=True,
                        help_text="Anchor: per-chord comment.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="charts.chordevent",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="replies",
                        to="charts.chartcomment",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="chartcomment",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(
                        song__isnull=False,
                        section__isnull=True,
                        chord_event__isnull=True,
                    )
                    | models.Q(
                        song__isnull=True,
                        section__isnull=False,
                        chord_event__isnull=True,
                    )
                    | models.Q(
                        song__isnull=True,
                        section__isnull=True,
                        chord_event__isnull=False,
                    )
                ),
                name="chartcomment_one_anchor",
            ),
        ),
        migrations.AddIndex(
            model_name="chartcomment",
            index=models.Index(
                fields=["song", "created_at"],
                name="chartcomment_song_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="chartcomment",
            index=models.Index(
                fields=["section", "created_at"],
                name="chartcomment_section_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="chartcomment",
            index=models.Index(
                fields=["chord_event", "created_at"],
                name="chartcomment_chord_idx",
            ),
        ),
    ]
