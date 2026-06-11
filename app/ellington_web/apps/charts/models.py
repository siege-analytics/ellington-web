"""Chart models — Songbook → Song → Section → Measure → ChordEvent.

Scaffolding only. No ingestion logic (iReal Pro parser is its own
ticket); no consumer logic (sub-3 / sub-4 don't read these yet); no
data populated. Every model has the right fields + admin pages so
future tickets surgically fill them in.

The chain reflects how a Real-Book / iReal-Pro chart is structurally
decomposed:

    Songbook ("Real Book Vol 1")
      └── Song ("All The Things You Are", key=Ab, time_sig=4/4, form=AABA)
            └── Section ("A", order_index=0, measure_count=8)
                  └── Measure (number_in_section=1)
                        └── ChordEvent (beat=1.0, chord_symbol="Fm7", duration=4)

The ``voicing_reference`` JSONField on ChordEvent is the eventual
hook into the plugin's ``voicings.json`` — empty for now; sub-3
ingestion or the comparator's eventual "what voicing did the user
play?" projection can fill it later.
"""

from __future__ import annotations

from django.db import models


# ---------------------------------------------------------------------------
# Enums (kept as text choices so admin renders human-readable values)
# ---------------------------------------------------------------------------


class ImportSource(models.TextChoices):
    REAL_BOOK_V1 = "real-book-v1", "Real Book Vol 1"
    REAL_BOOK_V2 = "real-book-v2", "Real Book Vol 2"
    REAL_BOOK_V3 = "real-book-v3", "Real Book Vol 3"
    NEW_REAL_BOOK = "new-real-book", "New Real Book"
    IREAL_PRO = "ireal-pro", "iReal Pro forum import"
    SIBELIUS = "sibelius", "Sibelius export"
    MUSESCORE = "musescore", "MuseScore export"
    HAND_ENTERED = "hand-entered", "Hand-entered"
    OTHER = "other", "Other / unknown"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Songbook(models.Model):
    slug = models.SlugField(unique=True, max_length=64)
    title = models.CharField(max_length=255)
    publisher = models.CharField(max_length=255, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"Songbook({self.slug})"


class Song(models.Model):
    slug = models.SlugField(unique=True, max_length=128)
    title = models.CharField(max_length=255)
    composer = models.CharField(max_length=255, blank=True)
    lyricist = models.CharField(max_length=255, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)

    # Canonical key (e.g. "C", "Bb", "F#m"). Free-form — keys-with-mode are
    # easier as strings than as a fenced enum.
    key = models.CharField(max_length=8, blank=True)

    # Free-form. Most charts are "4/4" but waltzes / jazz-waltzes / etc happen.
    time_signature = models.CharField(max_length=8, blank=True, default="4/4")
    default_tempo_bpm = models.PositiveIntegerField(null=True, blank=True)

    # Form label — "AABA", "ABAC", "blues-12", "modal", "through-composed", etc.
    form = models.CharField(max_length=64, blank=True)

    # Many songs live in multiple songbooks; FK is the "canonical" source
    # from which this entry was ingested.
    songbook = models.ForeignKey(
        Songbook,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="songs",
    )
    import_source = models.CharField(
        max_length=32,
        choices=ImportSource.choices,
        default=ImportSource.OTHER,
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "slug"]

    def __str__(self) -> str:
        return f"Song({self.slug})"


class Section(models.Model):
    """A formal section of a song — A, A', B, intro, outro, vamp, etc."""

    song = models.ForeignKey(
        Song,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    label = models.CharField(
        max_length=32,
        help_text="A, A', B, intro, outro, vamp, coda, ...",
    )
    order_index = models.PositiveSmallIntegerField(
        help_text="0-based order within the song's form.",
    )
    measure_count = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Number of measures in this section. May be left null when ingesting from a source that doesn't carry it.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["song", "order_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["song", "order_index"],
                name="unique_section_order_per_song",
            ),
        ]

    def __str__(self) -> str:
        return f"Section({self.song.slug}:{self.label}@{self.order_index})"


class Measure(models.Model):
    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name="measures",
    )
    number_in_section = models.PositiveSmallIntegerField(
        help_text="1-based measure index within the section.",
    )

    # Optional override for compound-meter songs that change in this measure.
    time_signature_override = models.CharField(
        max_length=8,
        blank=True,
        help_text='Only set when this measure differs from the song\'s default (e.g. one 2/4 bar in a 4/4 song).',
    )

    # Repeat markers: "open" (start repeat), "close" (end repeat),
    # "first-ending", "second-ending", or blank.
    repeat_marker = models.CharField(max_length=16, blank=True)

    class Meta:
        ordering = ["section", "number_in_section"]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "number_in_section"],
                name="unique_measure_per_section",
            ),
        ]

    def __str__(self) -> str:
        return f"Measure({self.section.song.slug}:{self.section.label}:{self.number_in_section})"


class ChordEvent(models.Model):
    """A chord at a specific beat position within a measure.

    ``voicing_reference`` is intentionally a JSONField rather than a FK
    — it'll eventually point at the plugin's voicings.json catalog, but
    we don't model voicings as Django rows yet. When sub-3 ingestion
    runs, the JSON shape can be ``{"voicing_id": "..."}``; when the
    comparator wants to enrich, it can stuff its own keys in.
    """

    measure = models.ForeignKey(
        Measure,
        on_delete=models.CASCADE,
        related_name="chord_events",
    )
    beat = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        help_text="1-indexed beat within the measure. 1.0 = downbeat; 2.5 = 'and' of beat 2.",
    )
    chord_symbol = models.CharField(
        max_length=32,
        help_text="Free-form chord symbol — 'Cmaj7', 'Dm7b5', 'G7#9b13', etc.",
    )
    duration_beats = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Beats this chord sounds for. Often inferred from the next ChordEvent's beat; null = 'until next event or end of measure'.",
    )

    # Voicing pin (optional). Used by the comparator's eventual
    # "is the user playing the recommended voicing?" pass.
    voicing_reference = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Forward-compatible voicing pointer. v0 shape: {} (no opinion). "
            "Future shapes: {'voicing_id': '<plugin slug>'} or "
            "{'voicing_style_tags': [...]} for soft binding."
        ),
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["measure", "beat"]
        constraints = [
            models.UniqueConstraint(
                fields=["measure", "beat"],
                name="unique_chord_event_per_beat",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"ChordEvent({self.measure.section.song.slug}:"
            f"{self.measure.section.label}:m{self.measure.number_in_section}"
            f":b{self.beat}:{self.chord_symbol})"
        )
