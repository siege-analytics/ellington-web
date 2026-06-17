"""Engine-rules catalog.

Models mirror the plugin's published JSON shape (firing-spec v0.1 at
``plugin/docs/engine-rules-firing-spec.md`` on
``musescore4-chord-library-plugin``). Loaded into Postgres by the
``sync_plugin_catalogs`` management command from a pinned GitHub
Release of the plugin repo (e.g. ``engine-rules-v0.1.0``).

Per the firing spec:

- ``preference`` is a signed Likert in ``[-2, +2]``. Polarity is
  derived: ``"avoid"`` when ``preference < 0``, ``"positive"`` when
  ``preference > 0``, ``"neutral"`` when ``= 0``. Stored as the integer;
  callers compute polarity via :meth:`EngineRule.polarity`.
- ``quality_binding`` is canonical chord-quality tokens only (post
  plugin #555 migration). The sync command applies an alias table from
  the firing spec to legacy values during the transition window.
- ``applicability_reasons`` carries non-canonical hints (e.g. Laukens's
  ``["voice_leading", "clarity"]``) that the plugin's #555 migration
  split off ``quality_binding``. Optional; empty for most rules.

This module is data-only — no firing logic. The engine lives in
``apps.engine_rules.engine`` and lands in PR 2 of #97 once the
conformance fixture (``expected-fires.json``) is populated upstream.
"""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


PREFERENCE_AVOID_STRONG = -2
PREFERENCE_AVOID_WEAK = -1
PREFERENCE_NEUTRAL = 0
PREFERENCE_RECOMMEND_WEAK = 1
PREFERENCE_RECOMMEND_STRONG = 2


class EngineRulesBundle(models.Model):
    """One imported plugin release. Captures provenance per sync run.

    Multiple bundles can coexist in the DB; the active set is whichever
    ``EngineRule`` rows have ``is_active=True``. Re-importing the same
    bundle is idempotent via the ``(plugin_commit_sha, bundle_version)``
    uniqueness constraint.
    """

    bundle_version = models.CharField(
        max_length=32,
        help_text="From manifest.bundle_version (e.g. '0.1.0').",
    )
    schema_version = models.CharField(
        max_length=16,
        help_text="From manifest.schema_version. sync_plugin_catalogs"
        " refuses bundles whose min_consumer_version is greater than"
        " the consumer's declared version.",
    )
    plugin_commit_sha = models.CharField(
        max_length=40,
        help_text="From manifest.plugin_commit_sha — the chord-library"
        " plugin commit the bundle was built from.",
    )
    built_at = models.DateTimeField(
        help_text="From manifest.built_at — when the plugin's release"
        " action emitted this bundle.",
    )
    total_rules = models.PositiveIntegerField(
        help_text="From manifest.total_rules — sanity check that the"
        " bundle's contents matched its declared count.",
    )
    manifest = models.JSONField(
        help_text="The full manifest.json content, preserved so future"
        " consumers can read forward-compatible fields without a"
        " schema migration."
    )
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-imported_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["plugin_commit_sha", "bundle_version"],
                name="enginerulesbundle_sha_ver_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"EngineRulesBundle({self.bundle_version}/{self.plugin_commit_sha[:8]})"


class EngineRule(models.Model):
    """One rule from the plugin's engine-rules corpus.

    Identified by ``(plugin_commit_sha, rule_id)`` — a re-import from a
    new bundle creates a new row even for an unchanged rule_id, so
    historical ``RuleFire`` rows (in ``apps.rule_review``) keep
    pointing at the exact rule version they fired against.
    """

    bundle = models.ForeignKey(
        EngineRulesBundle,
        on_delete=models.PROTECT,
        related_name="rules",
        help_text="The bundle this rule was imported from. PROTECT"
        " because deleting a bundle out from under a RuleFire history"
        " would orphan ground-truth confirmation data.",
    )

    # Master FK keys off slug. Plugin #553 normalized master_ids, so
    # the sync command upserts Master.slug to match plugin master_id.
    # Master must already exist (sync_plugin_catalogs imports Masters
    # before EngineRules in the same run).
    master = models.ForeignKey(
        "styles.Master",
        on_delete=models.PROTECT,
        related_name="engine_rules",
        to_field="slug",
        db_column="master_slug",
    )

    work_id = models.CharField(
        max_length=128,
        help_text="From the rule's source work (e.g. 'complete-chord-melody').",
    )
    rule_id = models.CharField(
        max_length=128,
        help_text="Plugin-side stable rule identifier within (master, work).",
    )

    name = models.CharField(max_length=255)

    # Signed Likert: -2 strong avoid .. +2 strong recommend.
    # Polarity derived (see ``polarity`` property below).
    preference = models.SmallIntegerField(
        validators=[
            MinValueValidator(PREFERENCE_AVOID_STRONG),
            MaxValueValidator(PREFERENCE_RECOMMEND_STRONG),
        ],
        help_text="Signed Likert. -2 strong avoid, -1 weak avoid, 0"
        " neutral, +1 weak recommend, +2 strong recommend. Polarity"
        " (avoid vs positive) is derived from the sign by callers.",
    )

    # Canonical chord-quality tokens only (post plugin #555 migration).
    # Until #555 lands, the sync command applies an alias table.
    quality_binding = ArrayField(
        models.CharField(max_length=32),
        default=list,
        blank=True,
        help_text="Canonical chord-quality tokens this rule applies to"
        " (e.g. ['dom7', 'dom7b9']). Empty array = applies to any"
        " quality. Hard prefilter at firing time.",
    )

    # Non-canonical hints split off quality_binding in plugin #555 —
    # e.g. Laukens's "voice_leading" / "clarity". Optional; mostly empty.
    applicability_reasons = ArrayField(
        models.CharField(max_length=64),
        default=list,
        blank=True,
        help_text="Non-canonical applicability hints. The firing engine"
        " doesn't use these for matching; they're surfaced in the"
        " review UI for rules whose 'when' is broader than their"
        " intended scope.",
    )

    when_predicate = models.JSONField(
        help_text="Plugin-side 'when' predicate — a dict of dotted-key"
        " dimensions to literal/array/'any' values. The firing engine"
        " (PR 2) matches this against the slice's facets."
    )
    then_action = models.JSONField(
        help_text="Plugin-side 'then' action — the voicing suggestion"
        " or proscription the rule emits when it fires.",
    )

    falsifier = models.TextField(
        blank=True,
        help_text="Prose statement of what would falsify the rule."
        " Not machine-checked in v1; surfaced in the review UI.",
    )
    anchor = models.TextField(
        blank=True,
        help_text="Verbatim short quote from the source work that"
        " warrants the rule. Surfaced verbatim in the review UI.",
    )
    source_page = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Page number in the source work the anchor was"
        " extracted from. Used by the review UI to link to the source"
        " (plugin #550) once the deep-link locator ships.",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="False for rules deprecated by a later bundle. Never"
        " deleted — preserves historical RuleFire→EngineRule joins.",
    )

    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["master__slug", "work_id", "rule_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["bundle", "master", "work_id", "rule_id"],
                name="enginerule_bundle_master_work_rule_unique",
            ),
        ]
        indexes = [
            # Firing path filters by (master, is_active) on the
            # majority of queries.
            models.Index(
                fields=["master", "is_active"],
                name="enginerule_master_active_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"EngineRule({self.master_id}:{self.work_id}:{self.rule_id})"

    @property
    def polarity(self) -> str:
        """Derived polarity per firing-spec v0.1.

        Returns ``"avoid"`` for negative preferences, ``"positive"``
        for positive, ``"neutral"`` for zero. The firing engine and the
        review UI use this rather than re-deriving every time.
        """
        if self.preference < 0:
            return "avoid"
        if self.preference > 0:
            return "positive"
        return "neutral"


__all__ = [
    "EngineRule",
    "EngineRulesBundle",
    "PREFERENCE_AVOID_STRONG",
    "PREFERENCE_AVOID_WEAK",
    "PREFERENCE_NEUTRAL",
    "PREFERENCE_RECOMMEND_WEAK",
    "PREFERENCE_RECOMMEND_STRONG",
]
