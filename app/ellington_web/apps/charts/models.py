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

from django.conf import settings
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
    OMR_PDF = "omr-pdf", "PDF scan via OMR (omr-leadsheet)"
    HAND_ENTERED = "hand-entered", "Hand-entered"
    OTHER = "other", "Other / unknown"


class ChartImportStatus(models.TextChoices):
    """Lifecycle of a multi-page PDF chart import.

    Mirrors the Recording.analysis_status shape from #67/#69 but adds
    ``PARTIAL`` because a multi-page scan (Real Book, fake-book, etc.)
    realistically lands with some pages succeeded and some failed —
    omr-leadsheet's per-page accuracy is not 100%. A practitioner who
    uploaded a 30-page book and got 28 useful Songs is better off than
    one who got nothing because page 7 confused Audiveris.

    ``PENDING`` — created, not yet enqueued.
    ``QUEUED`` — Celery task ID is on ``task_id``, worker hasn't started.
    ``RUNNING`` — orchestrator is currently extracting pages.
    ``COMPLETE`` — every page succeeded; ``pages_succeeded == page_count``.
    ``PARTIAL`` — at least one page succeeded AND at least one failed.
    ``FAILED`` — zero pages succeeded (PDF unreadable, OMR returned nothing).
    """

    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETE = "complete", "Complete"
    PARTIAL = "partial", "Partial (some pages failed)"
    FAILED = "failed", "Failed"


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
    # When this Song was extracted by a Phase 4-PDF OMR run, the
    # producing ChartImport is here. Null for hand-entered Songs and
    # for the Phase 1 / Phase 4-MS imports that don't go through
    # ChartImport. ``on_delete=SET_NULL`` because a Song may already
    # be referenced by a PracticeSession by the time someone deletes
    # the original ChartImport, and we'd rather orphan the import
    # record than cascade-delete the practitioner's chart history.
    import_run = models.ForeignKey(
        "ChartImport",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="songs",
        help_text=(
            "Multi-page OMR import this Song was extracted from. "
            "Null for Songs not imported via Phase 4-PDF."
        ),
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


# ---------------------------------------------------------------------------
# Phase 4-PDF — ChartImport (multi-page PDF → N Songs in one Songbook)
# ---------------------------------------------------------------------------


class ChartImport(models.Model):
    """One PDF lead-sheet upload going through the omr-leadsheet pipeline.

    Phase 4-PDF (#70) routes a multi-page PDF (e.g. a Real Book scan)
    through omr-leadsheet, which extracts one ``.mscz`` per page. Each
    successful page lands as a Song row in ``source_songbook``; the
    one-to-many relation is ``self.songs`` (the reverse of
    ``Song.import_run``).

    State machine (mirrors the Recording.analysis_status pattern from
    #67/#69, plus a ``PARTIAL`` terminal state for the realistic
    multi-page-with-some-failures case):

        PENDING ──► QUEUED ──► RUNNING ──► COMPLETE
                                       │       │
                                       │       ├──► PARTIAL  (≥1 succeeded, ≥1 failed)
                                       │       └──► FAILED   (0 succeeded)
                                       └──────► FAILED       (orchestrator crash)

    Idempotency: identical PDF uploads (matched by ``file_ref``
    content-addressed SHA-256) reuse the existing ``ChartImport`` row
    instead of creating a duplicate. The upload view enforces this;
    the model just provides the unique constraint.

    Error reporting: per-page warnings and failures live in
    ``error_log`` as structured JSON. We deliberately do NOT mutate
    any user-editable text field with error details — that pattern
    caused the concurrent-write race the #67/#69 review caught.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chart_imports",
        help_text="The practitioner who uploaded the PDF.",
    )

    # Content-addressed reference (SHA-256 → MEDIA_ROOT/pdf_upload/<sha>.pdf).
    # Same opaque-string convention as the audio uploader so the storage
    # layer can rotate (local → S3 → MinIO) without a schema migration.
    file_ref = models.CharField(
        max_length=255,
        unique=True,
        help_text="Content-addressed path (SHA-256) of the source PDF.",
    )

    # The Songbook every extracted Song lands in. Set by the upload
    # view from the form input — null until the upload completes
    # (which happens before the orchestrator dispatch, so in practice
    # this is always set on RUNNING / COMPLETE / PARTIAL / FAILED).
    source_songbook = models.ForeignKey(
        Songbook,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="chart_imports",
        help_text="Songbook receiving extracted Songs.",
    )

    status = models.CharField(
        max_length=16,
        choices=ChartImportStatus.choices,
        default=ChartImportStatus.PENDING,
    )

    # Celery task ID for cancel/retry. Cleared on terminal state.
    task_id = models.CharField(max_length=64, blank=True, default="")

    # Page bookkeeping. ``page_count`` is set after the orchestrator's
    # layout pass; until then it's null. The two counters drive the
    # COMPLETE vs PARTIAL vs FAILED resolution at the end of the run.
    page_count = models.PositiveIntegerField(null=True, blank=True)
    pages_succeeded = models.PositiveIntegerField(default=0)
    pages_failed = models.PositiveIntegerField(default=0)

    # Structured per-page error / warning log. Shape:
    #   {
    #     "page_warnings": {"<page_index>": ["...", "..."]},
    #     "page_failures": {"<page_index>": "error message"},
    #   }
    # Keyed by string page index because JSONField dict keys are
    # always strings on round-trip — keeping them strings here avoids
    # type confusion in the view layer.
    error_log = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        # Belt-and-suspenders: unique=True on file_ref already prevents
        # duplicate uploads of the same PDF; this index speeds the
        # per-user list view ("show me my recent imports").
        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="chartimport_user_recent_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"ChartImport({self.pk}:{self.status})"
