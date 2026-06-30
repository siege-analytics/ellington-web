"""Voicings corpus models (epic #186 Phase 2).

Parallels ``apps.engine_rules`` in shape: ``VoicingBundle`` carries
provenance for one ingest run; ``Voicing`` is the per-row payload.
Mirrors the plugin's locked schema at
``schema/voicings.schema.json``.

Notable schema gap vs engine_rules: the plugin's ``voicings.json``
ships only ``{"voicings": [...]}`` at the top level — there is no
manifest block carrying ``bundle_version`` / ``plugin_commit_sha`` /
``built_at``. Phase 2 synthesizes those fields from the plugin git
SHA + file mtime at sync time (see
``apps.voicings.management.commands.sync_voicings`` docstring). A
follow-up plugin ticket will align the contracts so the producer
emits a manifest parallel to engine_rules.
"""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models


class VoicingBundle(models.Model):
    """One imported voicings-corpus snapshot. Provenance per sync run.

    Multiple bundles can coexist; the active set is whichever ``Voicing``
    rows have ``is_active=True``. Re-importing the same plugin SHA is
    idempotent via the ``(plugin_commit_sha,)`` uniqueness constraint.
    """

    plugin_commit_sha = models.CharField(
        max_length=40,
        help_text="Plugin git SHA the voicings.json was fetched from."
        " Synthesized at sync time since voicings.json has no top-level"
        " manifest block (engine_rules.json does — contract gap to"
        " close upstream).",
    )
    source_url = models.CharField(
        max_length=512,
        help_text="URL the voicings.json was fetched from (raw GitHub or"
        " release asset). Stored verbatim for audit.",
    )
    built_at = models.DateTimeField(
        help_text="File mtime in the plugin repo at fetch time, OR"
        " explicit override via --built-at on sync. Mirrors"
        " ``EngineRulesBundle.built_at``.",
    )
    total_voicings = models.PositiveIntegerField(
        help_text="Sanity check — the importer asserts this matches the"
        " number of rows ingested before committing.",
    )
    raw_top_level = models.JSONField(
        help_text="The voicings.json top-level dict minus the ``voicings``"
        " array. Empty today; future-proof for when the plugin adds a"
        " manifest block."
    )
    is_active = models.BooleanField(
        default=False,
        help_text="True for the bundle whose Voicing rows are surfaced"
        " in browse views. Only one bundle is active at a time."
        " sync_voicings deactivates prior actives on success.",
    )
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-imported_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["plugin_commit_sha"],
                name="voicingbundle_sha_unique",
            ),
        ]

    def __str__(self) -> str:
        active = " active" if self.is_active else ""
        return f"VoicingBundle({self.plugin_commit_sha[:8]}{active})"


class Voicing(models.Model):
    """One guitar chord voicing from the plugin corpus.

    All voicings store ``root="C"`` per plugin convention; consumer-side
    transposition is the renderer's job. ``chord_quality`` and
    ``category`` are stored as free-text CharFields to match the
    plugin's open enum (the plugin schema explicitly allows imports to
    introduce new values).
    """

    bundle = models.ForeignKey(
        VoicingBundle,
        on_delete=models.PROTECT,
        related_name="voicings",
        help_text="Source bundle. PROTECT so deleting a bundle out from"
        " under future cross-references (Phase 2b/3 will FK from"
        " PedagogueConfirmation) doesn't orphan rows.",
    )

    voicing_id = models.CharField(
        max_length=128,
        help_text="Plugin's ``id`` field (e.g. ``c13b9-cm6-altered-6str-26``)."
        " Unique within a bundle.",
    )
    name = models.CharField(
        max_length=256,
        help_text="Human-readable name (e.g. ``C7 — Shell 137 — E str``).",
    )
    chord_quality = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Free-text chord quality token. Most rules bind to"
        " ``maj7`` / ``dom7`` / ``min7`` etc., but the plugin schema"
        " allows any string (e.g. ``dom7b9``).",
    )
    root = models.CharField(
        max_length=2,
        db_index=True,
        help_text="Plugin stores everything at ``C``. Indexed for the"
        " day transpose-on-store lands (not Phase 2).",
    )
    category = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Voicing category (e.g. ``shell``, ``drop2``,"
        " ``drop3``, ``extended``, ``altered``, ``quartal``).",
    )
    suitable_modes = ArrayField(
        models.CharField(max_length=32),
        default=list,
        blank=True,
        help_text="``chord-melody`` / ``comping`` / ``solo-guitar`` /"
        " ``duo``. Soft hint per plugin schema, not a hard filter.",
    )

    strings = models.PositiveSmallIntegerField(
        help_text="Instrument string count (6 = standard, 7 = Van Eps).",
    )
    tuning = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Tuning config name (matches plugin ``config/tunings/``)."
        " Empty = standard.",
    )
    fret_number = models.PositiveSmallIntegerField(
        help_text="Starting fret for the diagram (row 1).",
    )
    visible_frets = models.PositiveSmallIntegerField(
        help_text="Number of frets shown in the diagram.",
    )

    dots = models.JSONField(
        help_text="List of ``{string, fret}`` dicts — fingered positions."
        " Stored as JSON since each entry is a small object.",
    )
    mutes = ArrayField(
        models.PositiveSmallIntegerField(),
        default=list,
        blank=True,
        help_text="String numbers muted (X above the nut).",
    )
    open_strings = ArrayField(
        models.PositiveSmallIntegerField(),
        default=list,
        blank=True,
        help_text="String numbers played open (O above the nut). Named"
        " ``open_strings`` to avoid Python's builtin ``open``.",
    )

    notes = ArrayField(
        models.CharField(max_length=4),
        default=list,
        blank=True,
        help_text="Note names sounding, low-to-high (e.g."
        " ``['C', 'E', 'Bb', 'Db', 'E', 'A']``).",
    )
    intervals = ArrayField(
        models.CharField(max_length=8),
        default=list,
        blank=True,
        help_text="Intervals above root for each sounding note (e.g."
        " ``['1', '3', 'b7', 'b9']``).",
    )
    tags = ArrayField(
        models.CharField(max_length=64),
        default=list,
        blank=True,
        help_text="Free-text labels (e.g. ``calculated``,"
        " ``laukens-coverage``).",
    )
    also_qualities = ArrayField(
        models.CharField(max_length=64),
        default=list,
        blank=True,
        help_text="Additional chord_quality tokens this voicing satisfies"
        " (the plugin's ranker uses this for substitution).",
    )
    shape_id = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Plugin's geometric-shape dedup hash. Empty when the"
        " plugin didn't emit one.",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Mirrors bundle.is_active at ingest time. Browse views"
        " filter on this.",
    )

    class Meta:
        ordering = ["chord_quality", "category", "voicing_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["bundle", "voicing_id"],
                name="voicing_bundle_id_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["chord_quality", "category"],
                name="voicing_quality_cat_idx",
            ),
            models.Index(
                fields=["is_active", "chord_quality"],
                name="voicing_active_quality_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Voicing({self.voicing_id})"


__all__ = ["Voicing", "VoicingBundle"]
