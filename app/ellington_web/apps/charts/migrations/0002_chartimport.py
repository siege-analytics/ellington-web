"""Phase 4-PDF foundation (#80) — ChartImport + Song.import_run FK.

Adds:
    - ChartImport model (multi-page PDF → N Songs in one Songbook)
    - ChartImportStatus enum values (PENDING/QUEUED/RUNNING/COMPLETE/PARTIAL/FAILED)
    - ImportSource.OMR_PDF choice on Song.import_source
    - Song.import_run FK → ChartImport (null, SET_NULL)
    - Composite index on (user, -created_at) for the per-user list view

Per Q1/Q2/Q3 decisions on #70 (see issue comment 4712606705):
    Q1 — Python orchestrator (subprocess only for Audiveris JVM)
    Q2 — Keep PDF on disk at MEDIA_ROOT/pdf_upload/{sha256}.pdf
    Q3 — Multi-page from v1; one PDF → N Songs in one Songbook
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("charts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChartImport",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "file_ref",
                    models.CharField(
                        help_text="Content-addressed path (SHA-256) of the source PDF.",
                        max_length=255,
                        unique=True,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("complete", "Complete"),
                            ("partial", "Partial (some pages failed)"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("task_id", models.CharField(blank=True, default="", max_length=64)),
                ("page_count", models.PositiveIntegerField(blank=True, null=True)),
                ("pages_succeeded", models.PositiveIntegerField(default=0)),
                ("pages_failed", models.PositiveIntegerField(default=0)),
                ("error_log", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "source_songbook",
                    models.ForeignKey(
                        blank=True,
                        help_text="Songbook receiving extracted Songs.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="chart_imports",
                        to="charts.songbook",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        help_text="The practitioner who uploaded the PDF.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chart_imports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="chartimport",
            index=models.Index(
                fields=["user", "-created_at"],
                name="chartimport_user_recent_idx",
            ),
        ),
        migrations.AlterField(
            model_name="song",
            name="import_source",
            field=models.CharField(
                choices=[
                    ("real-book-v1", "Real Book Vol 1"),
                    ("real-book-v2", "Real Book Vol 2"),
                    ("real-book-v3", "Real Book Vol 3"),
                    ("new-real-book", "New Real Book"),
                    ("ireal-pro", "iReal Pro forum import"),
                    ("sibelius", "Sibelius export"),
                    ("musescore", "MuseScore export"),
                    ("omr-pdf", "PDF scan via OMR (omr-leadsheet)"),
                    ("hand-entered", "Hand-entered"),
                    ("other", "Other / unknown"),
                ],
                default="other",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="song",
            name="import_run",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Multi-page OMR import this Song was extracted from. "
                    "Null for Songs not imported via Phase 4-PDF."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="songs",
                to="charts.chartimport",
            ),
        ),
    ]
