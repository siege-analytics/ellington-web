"""TeacherStudent + RecordingCommentAcknowledgement
(epic #96 sub-ticket i / #126)."""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("practice", "0006_studio_studiomember"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TeacherStudent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                (
                    "teacher",
                    models.ForeignKey(
                        help_text="The teacher in the relationship.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="teaches",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        help_text="The student being taught.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="studies_with",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "studio",
                    models.ForeignKey(
                        blank=True, null=True,
                        help_text=(
                            "Optional Studio scope. When set, the"
                            " relationship is visible to other members"
                            " of the Studio."
                        ),
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="teacher_student_relationships",
                        to="practice.studio",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="teacherstudent",
            constraint=models.UniqueConstraint(
                condition=models.Q(("ended_at__isnull", True)),
                fields=("teacher", "student", "studio"),
                name="teacherstudent_active_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="teacherstudent",
            constraint=models.CheckConstraint(
                condition=models.Q(("teacher", models.F("student")), _negated=True),
                name="teacherstudent_no_self_teach",
            ),
        ),
        migrations.AddIndex(
            model_name="teacherstudent",
            index=models.Index(
                fields=["student", "teacher"],
                name="teacherstudent_student_idx",
            ),
        ),
        migrations.CreateModel(
            name="RecordingCommentAcknowledgement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                ("acknowledged_at", models.DateTimeField(auto_now_add=True)),
                (
                    "note",
                    models.TextField(
                        blank=True,
                        help_text=(
                            "Optional reply note. Distinct from a comment"
                            " reply because it's an acknowledgement-with-"
                            "context, not a thread contribution."
                        ),
                    ),
                ),
                (
                    "acknowledged_by",
                    models.ForeignKey(
                        help_text=(
                            "The student (or other recipient) confirming"
                            " they read the teacher's comment."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="comment_acknowledgements",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "comment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="acknowledgements",
                        to="practice.recordingcomment",
                    ),
                ),
            ],
            options={
                "ordering": ["-acknowledged_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="recordingcommentacknowledgement",
            constraint=models.UniqueConstraint(
                fields=("comment", "acknowledged_by"),
                name="recordingcommentack_comment_user_unique",
            ),
        ),
    ]
