"""Engine-rules data-layer initial migration (Phase 6-A PR 1 of #97).

Creates EngineRulesBundle + EngineRule tables. No data import — that's
the sync_plugin_catalogs extension landing alongside this migration.
"""

from __future__ import annotations

import django.contrib.postgres.fields
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        # Master FK targets styles.Master.slug; depend on whichever
        # styles migration ships the Master model.
        ("styles", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="EngineRulesBundle",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "bundle_version",
                    models.CharField(
                        help_text="From manifest.bundle_version (e.g. '0.1.0').",
                        max_length=32,
                    ),
                ),
                (
                    "schema_version",
                    models.CharField(
                        help_text=(
                            "From manifest.schema_version. sync_plugin_catalogs"
                            " refuses bundles whose min_consumer_version is"
                            " greater than the consumer's declared version."
                        ),
                        max_length=16,
                    ),
                ),
                (
                    "plugin_commit_sha",
                    models.CharField(
                        help_text=(
                            "From manifest.plugin_commit_sha — the chord-library"
                            " plugin commit the bundle was built from."
                        ),
                        max_length=40,
                    ),
                ),
                (
                    "built_at",
                    models.DateTimeField(
                        help_text=(
                            "From manifest.built_at — when the plugin's release"
                            " action emitted this bundle."
                        ),
                    ),
                ),
                (
                    "total_rules",
                    models.PositiveIntegerField(
                        help_text=(
                            "From manifest.total_rules — sanity check that the"
                            " bundle's contents matched its declared count."
                        ),
                    ),
                ),
                (
                    "manifest",
                    models.JSONField(
                        help_text=(
                            "The full manifest.json content, preserved so future"
                            " consumers can read forward-compatible fields"
                            " without a schema migration."
                        ),
                    ),
                ),
                ("imported_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-imported_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="enginerulesbundle",
            constraint=models.UniqueConstraint(
                fields=("plugin_commit_sha", "bundle_version"),
                name="enginerulesbundle_sha_ver_unique",
            ),
        ),
        migrations.CreateModel(
            name="EngineRule",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "work_id",
                    models.CharField(
                        help_text=(
                            "From the rule's source work (e.g."
                            " 'complete-chord-melody')."
                        ),
                        max_length=128,
                    ),
                ),
                (
                    "rule_id",
                    models.CharField(
                        help_text=(
                            "Plugin-side stable rule identifier within"
                            " (master, work)."
                        ),
                        max_length=128,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "preference",
                    models.SmallIntegerField(
                        help_text=(
                            "Signed Likert. -2 strong avoid, -1 weak avoid,"
                            " 0 neutral, +1 weak recommend, +2 strong"
                            " recommend. Polarity (avoid vs positive) is"
                            " derived from the sign by callers."
                        ),
                        validators=[
                            django.core.validators.MinValueValidator(-2),
                            django.core.validators.MaxValueValidator(2),
                        ],
                    ),
                ),
                (
                    "quality_binding",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=32),
                        blank=True,
                        default=list,
                        help_text=(
                            "Canonical chord-quality tokens this rule applies"
                            " to (e.g. ['dom7', 'dom7b9']). Empty array ="
                            " applies to any quality. Hard prefilter at firing"
                            " time."
                        ),
                        size=None,
                    ),
                ),
                (
                    "applicability_reasons",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=64),
                        blank=True,
                        default=list,
                        help_text=(
                            "Non-canonical applicability hints. The firing"
                            " engine doesn't use these for matching; they're"
                            " surfaced in the review UI for rules whose 'when'"
                            " is broader than their intended scope."
                        ),
                        size=None,
                    ),
                ),
                (
                    "when_predicate",
                    models.JSONField(
                        help_text=(
                            "Plugin-side 'when' predicate — a dict of"
                            " dotted-key dimensions to literal/array/'any'"
                            " values. The firing engine (PR 2) matches this"
                            " against the slice's facets."
                        ),
                    ),
                ),
                (
                    "then_action",
                    models.JSONField(
                        help_text=(
                            "Plugin-side 'then' action — the voicing"
                            " suggestion or proscription the rule emits when"
                            " it fires."
                        ),
                    ),
                ),
                (
                    "falsifier",
                    models.TextField(
                        blank=True,
                        help_text=(
                            "Prose statement of what would falsify the rule."
                            " Not machine-checked in v1; surfaced in the"
                            " review UI."
                        ),
                    ),
                ),
                (
                    "anchor",
                    models.TextField(
                        blank=True,
                        help_text=(
                            "Verbatim short quote from the source work that"
                            " warrants the rule. Surfaced verbatim in the"
                            " review UI."
                        ),
                    ),
                ),
                (
                    "source_page",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text=(
                            "Page number in the source work the anchor was"
                            " extracted from. Used by the review UI to link"
                            " to the source (plugin #550) once the deep-link"
                            " locator ships."
                        ),
                        null=True,
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text=(
                            "False for rules deprecated by a later bundle."
                            " Never deleted — preserves historical"
                            " RuleFire→EngineRule joins."
                        ),
                    ),
                ),
                ("imported_at", models.DateTimeField(auto_now_add=True)),
                (
                    "bundle",
                    models.ForeignKey(
                        help_text=(
                            "The bundle this rule was imported from. PROTECT"
                            " because deleting a bundle out from under a"
                            " RuleFire history would orphan ground-truth"
                            " confirmation data."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rules",
                        to="engine_rules.enginerulesbundle",
                    ),
                ),
                (
                    "master",
                    models.ForeignKey(
                        db_column="master_slug",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="engine_rules",
                        to="styles.master",
                        to_field="slug",
                    ),
                ),
            ],
            options={
                "ordering": ["master__slug", "work_id", "rule_id"],
            },
        ),
        migrations.AddConstraint(
            model_name="enginerule",
            constraint=models.UniqueConstraint(
                fields=("bundle", "master", "work_id", "rule_id"),
                name="enginerule_bundle_master_work_rule_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="enginerule",
            index=models.Index(
                fields=["master", "is_active"],
                name="enginerule_master_active_idx",
            ),
        ),
    ]
