"""Initial migration for apps.rule_review (epic #96 / #98)."""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("engine_rules", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Response",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                (
                    "verdict",
                    models.CharField(
                        choices=[
                            ("accept", "Accept"),
                            ("close_but", "Close but not quite"),
                            ("reject", "Reject"),
                        ],
                        db_index=True,
                        help_text="3-state verdict per the focus-group methodology.",
                        max_length=16,
                    ),
                ),
                (
                    "rejection_axis",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("when", "The 'when' predicate matches the wrong contexts"),
                            ("then", "The 'then' action / voicing is wrong"),
                            ("preference", "The signed Likert preference is miscalibrated"),
                            ("quality_binding", "The chord-quality binding is wrong"),
                            ("anchor", "The anchor quote doesn't support the rule"),
                            ("overall", "The whole rule shouldn't exist"),
                        ],
                        default="",
                        help_text=(
                            "Which axis of the rule failed. Only set when"
                            " verdict != accept. Routes corpus fixes plugin-side."
                        ),
                        max_length=32,
                    ),
                ),
                (
                    "comment",
                    models.TextField(
                        blank=True,
                        help_text=(
                            "Free-text reasoning. The actual signal —"
                            " maintainer reads every comment and makes corpus calls."
                        ),
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "rule",
                    models.ForeignKey(
                        help_text="The rule being judged.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="responses",
                        to="engine_rules.enginerule",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        help_text=(
                            "The pedagogue who responded. PROTECT — preserve"
                            " ground-truth verdicts on user deletion."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rule_responses",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="response",
            constraint=models.UniqueConstraint(
                fields=("rule", "user"),
                name="response_rule_user_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="response",
            index=models.Index(
                fields=["rule", "verdict"],
                name="response_rule_verdict_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="response",
            index=models.Index(
                fields=["user", "-updated_at"],
                name="response_user_recent_idx",
            ),
        ),
        migrations.CreateModel(
            name="RuleComment",
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
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "author",
                    models.ForeignKey(
                        help_text=(
                            "Comment author. PROTECT — sentinel-anonymize"
                            " on user delete."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rule_comments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "rule",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="engine_rules.enginerule",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="replies",
                        to="rule_review.rulecomment",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="rulecomment",
            index=models.Index(
                fields=["rule", "created_at"],
                name="rulecomment_rule_chrono_idx",
            ),
        ),
    ]
