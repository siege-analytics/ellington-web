"""Three-axis style-selection model: master × style × idiom.

Per coordination with the plugin agent (siege-analytics/musescore4-chord-library-plugin#412):
- ``master`` = WHO teaches this (Joe Pass, Van Eps, ...)
- ``style`` = WHAT TRADITION this belongs to (bebop, bossa, gypsy, ...)
- ``idiom`` = PERFORMANCE CONTEXT (chord-melody, comping, single-line, ...)

The three axes are orthogonal. A user's ``StyleSelection`` picks a
``target_preset`` and a ``backing_preset`` (each a ``StylePreset``
that pins zero or more of the three axes). The ``Critique`` row is
written by the audio pipeline (sub-4) once it can detect what's
actually being played; the style comparator (sub-B) scores the
detected playing against the selection's expectations and produces
the structured commentary.

Until the plugin agent ships ``styles.json`` v1 (post-distillation
pass), Style / Idiom / Master rows are flagged ``is_placeholder=True``
and live as seed data. The catalog-sync command (sub-E) flips that
flag when it loads real prescriptive content from the plugin.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


# ---------------------------------------------------------------------------
# Catalog rows — cached locally; canonical source is the plugin's catalogs.
# Each carries ``schema_version`` so sub-E's loader can refuse incompatible
# major bumps.
# ---------------------------------------------------------------------------


class Master(models.Model):
    """A teacher / canonical player. Cached from plugin's masters.json."""

    slug = models.SlugField(unique=True, max_length=64)
    name = models.CharField(max_length=128)
    summary = models.TextField(blank=True)
    schema_version = models.CharField(max_length=16, default="v1")
    is_placeholder = models.BooleanField(
        default=True,
        help_text="True until catalog-sync replaces with real plugin data.",
    )
    extra = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Plugin-side fields not modelled as columns yet — "
            "prescriptive_lessons, example_masters, diagnostic_examples, "
            "etc. sync_plugin_catalogs writes the whole non-mapped subset "
            "here so consumers can read it via the .extra accessor without "
            "us having to migrate every time the plugin schema grows."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"Master({self.slug})"


class Style(models.Model):
    """A tradition (bebop, bossa, gypsy, cool-jazz, ...). The molecule.

    Voicing tags are the atom (live in voicings.json). A Style is a
    curated affinity map over those tags + a rhythmic / harmonic
    signature + structured divergence_notes against sibling styles.
    """

    slug = models.SlugField(unique=True, max_length=64)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    schema_version = models.CharField(max_length=16, default="v1")

    # Per-tag weight in [0, 1]+. Higher = more characteristic of this style.
    # Empty dict for a Style means "no opinions about which voicing tags it
    # favours" — comparator treats as neutral.
    voicing_style_tag_affinity = models.JSONField(default=dict, blank=True)

    # Free-form structured rhythmic profile. Suggested keys:
    #   onset_anticipation (str: "on-beat", "anticipated", "delayed", "mixed")
    #   subdivision (str: "8ths", "16ths", "shuffled-8ths")
    #   density (str: "sparse", "medium", "dense")
    # Final shape TBD per plugin agent's distillation output.
    rhythmic_signature = models.JSONField(default=dict, blank=True)

    # Free-form structured harmonic profile. Suggested keys:
    #   chromatic_motion_tolerance (str: "low", "medium", "high")
    #   substitution_density (str: ...)
    #   color_tone_preference (list[str])
    harmonic_signature = models.JSONField(default=dict, blank=True)

    # Structured cross-style commentary. Each entry:
    #   { "vs_style": "<slug>",
    #     "shared_dimensions": ["..."],
    #     "diverging_dimensions": ["..."],
    #     "characteristic_quote": "A bebop player would say..." }
    # The ``characteristic_quote`` is rendered verbatim by the LLM coach
    # (sub-5) when generating cross-style critique. Authored by the
    # plugin agent / project owner during distillation.
    divergence_notes = models.JSONField(default=list, blank=True)

    is_placeholder = models.BooleanField(
        default=True,
        help_text="True until catalog-sync replaces with real plugin data.",
    )
    extra = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Plugin-side fields not modelled as columns yet — "
            "prescriptive_lessons, example_masters, diagnostic_examples, "
            "etc. sync_plugin_catalogs writes the whole non-mapped subset "
            "here so consumers can read it via the .extra accessor without "
            "us having to migrate every time the plugin schema grows."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"Style({self.slug})"


class Idiom(models.Model):
    """A performance context: chord-melody, comping, single-line, ..."""

    slug = models.SlugField(unique=True, max_length=64)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    schema_version = models.CharField(max_length=16, default="v1")
    performance_context_metadata = models.JSONField(default=dict, blank=True)
    is_placeholder = models.BooleanField(
        default=True,
        help_text="True until catalog-sync replaces with real plugin data.",
    )
    extra = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Plugin-side fields not modelled as columns yet — "
            "prescriptive_lessons, example_masters, diagnostic_examples, "
            "etc. sync_plugin_catalogs writes the whole non-mapped subset "
            "here so consumers can read it via the .extra accessor without "
            "us having to migrate every time the plugin schema grows."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"Idiom({self.slug})"


# ---------------------------------------------------------------------------
# User-facing presets + selections + critiques
# ---------------------------------------------------------------------------


class StylePreset(models.Model):
    """A composable selection along the three axes. Any subset of axes may
    be set (at least one must be); none = invalid and rejected by full_clean().
    """

    slug = models.SlugField(unique=True, max_length=128)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    master = models.ForeignKey(
        Master,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="presets",
    )
    style = models.ForeignKey(
        Style,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="presets",
    )
    idiom = models.ForeignKey(
        Idiom,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="presets",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"StylePreset({self.slug})"

    def clean(self) -> None:
        if not (self.master_id or self.style_id or self.idiom_id):
            raise ValidationError(
                "At least one of master / style / idiom must be set."
            )

    @property
    def axis_summary(self) -> str:
        """Human-readable axis summary — useful for admin list_display."""
        parts: list[str] = []
        if self.master_id:
            parts.append(f"master={self.master.slug}")
        if self.style_id:
            parts.append(f"style={self.style.slug}")
        if self.idiom_id:
            parts.append(f"idiom={self.idiom.slug}")
        return " × ".join(parts) or "(no axes)"


class StyleSelection(models.Model):
    """A user's "play X against Y" session context. ``target_preset`` is
    what the user wants to play; ``backing_preset`` is what's coming out
    of the speakers (BIAB / iReal Pro / etc.). Comparator commentary
    triangulates between the two.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="style_selections",
    )
    target_preset = models.ForeignKey(
        StylePreset,
        on_delete=models.PROTECT,
        related_name="target_selections",
    )
    backing_preset = models.ForeignKey(
        StylePreset,
        on_delete=models.PROTECT,
        related_name="backing_selections",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return (
            f"StyleSelection(user={self.user_id}, "
            f"target={self.target_preset.slug}, "
            f"backing={self.backing_preset.slug})"
        )


class Critique(models.Model):
    """Comparator output for a passage of audio. Written by sub-4 (audio
    pipeline) once chord events are detected, OR by the smoke view
    (sub-D) for canned testing.
    """

    selection = models.ForeignKey(
        StyleSelection,
        on_delete=models.CASCADE,
        related_name="critiques",
    )
    style_match_score = models.FloatField(
        help_text="0.0–1.0: how well the detected playing matches target_preset.",
    )
    detected_axes = models.JSONField(
        default=dict,
        help_text=(
            "Comparator's read on what the user is ACTUALLY playing: "
            "{ 'master': {'slug': ..., 'confidence': ...}, "
            "  'style': {'slug': ..., 'confidence': ...}, "
            "  'idiom': {'slug': ..., 'confidence': ...} }"
        ),
    )
    commentary = models.TextField(
        blank=True,
        help_text=(
            "Structured commentary draft — divergence quotes + diagnostics. "
            "LLM coach (sub-5) renders these into prose later."
        ),
    )
    audio_input_ref = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Opaque reference to the audio passage. sub-4 populates.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Critique(selection={self.selection_id}, score={self.style_match_score:.2f})"
