"""Practice models — sessions, backing tracks, recordings, audio stems,
chord detections, and per-segment critiques.

Scaffolding only. The chain reflects how a practice loop will work in
production:

    PracticeSession (user picks a target_preset + an optional song)
      │
      ├── BackingTrack reference (the BIAB / iReal Pro audio under the user)
      │
      └── Recording (the user's audio coming in)
            │
            ├── AudioStem [sub-4 will write these — Demucs guitar/bass/drums split]
            │
            └── ChordDetection [sub-4 will write these — chord recognition output]

    PracticeSegment cuts a slice of the session for focused feedback. It
    ties together a Recording window + a ChordDetection batch + a
    Critique row (in apps.styles).

No consumer code writes any of these yet. sub-4 (audio pipeline) plugs
into ``Recording`` → emits ``AudioStem`` + ``ChordDetection``; sub-5
(LLM coach) reads the resulting Critique. This module gives them all
their landing pad.

File references are kept as opaque strings (``audio_ref``,
``file_ref``) instead of FileField/StorageObject because:
1. The storage layer is TBD (S3? in-cluster MinIO? local volume?)
2. We don't want to migrate the schema when storage rotates.
The string is meant to be a URL or a content-addressed digest — caller
decides.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BackingSource(models.TextChoices):
    BIAB = "biab", "Band-in-a-Box"
    IREAL_PRO = "ireal-pro", "iReal Pro"
    CUSTOM = "custom", "Custom (user-uploaded)"
    OTHER = "other", "Other"


class StemType(models.TextChoices):
    GUITAR = "guitar", "Guitar"
    BASS = "bass", "Bass"
    DRUMS = "drums", "Drums"
    VOCALS = "vocals", "Vocals"
    KEYS = "keys", "Keys"
    OTHER = "other", "Other"


class SessionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    ABANDONED = "abandoned", "Abandoned"


# ---------------------------------------------------------------------------
# Backing track (the rhythm-section context the user plays against)
# ---------------------------------------------------------------------------


class BackingTrack(models.Model):
    slug = models.SlugField(unique=True, max_length=128)
    title = models.CharField(max_length=255)
    source = models.CharField(
        max_length=32,
        choices=BackingSource.choices,
        default=BackingSource.OTHER,
    )
    audio_ref = models.CharField(
        max_length=512,
        blank=True,
        help_text="Opaque storage reference (URL / digest). Storage layer TBD.",
    )

    # Stylistic tags so the comparator's "you said play bossa over gypsy
    # backing" framing works.
    style = models.ForeignKey(
        "styles.Style",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backing_tracks",
    )
    idiom = models.ForeignKey(
        "styles.Idiom",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backing_tracks",
    )

    # Which chart this backing track is voicing. Optional — a backing
    # track may be a generic "blues in F" without referencing a specific
    # Song row.
    song = models.ForeignKey(
        "charts.Song",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backing_tracks",
    )

    tempo_bpm = models.PositiveIntegerField(null=True, blank=True)
    key = models.CharField(max_length=8, blank=True)
    time_signature = models.CharField(max_length=8, blank=True, default="4/4")
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"BackingTrack({self.slug})"


# ---------------------------------------------------------------------------
# Practice session — user + intent + backing context
# ---------------------------------------------------------------------------


class PracticeSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="practice_sessions",
    )
    song = models.ForeignKey(
        "charts.Song",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="practice_sessions",
        help_text="Optional — practice can be open-ended (no specific chart).",
    )

    # The user's stated target style. FK into apps.styles.StylePreset
    # so all three axes (master × style × idiom) are captured via one ref.
    target_preset = models.ForeignKey(
        "styles.StylePreset",
        on_delete=models.PROTECT,
        related_name="target_practice_sessions",
    )
    backing_track = models.ForeignKey(
        BackingTrack,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="practice_sessions",
    )

    status = models.CharField(
        max_length=16,
        choices=SessionStatus.choices,
        default=SessionStatus.ACTIVE,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return (
            f"PracticeSession(user={self.user_id}, "
            f"target={self.target_preset.slug}, status={self.status})"
        )


# ---------------------------------------------------------------------------
# Recording — the user's incoming audio
# ---------------------------------------------------------------------------


class Recording(models.Model):
    session = models.ForeignKey(
        PracticeSession,
        on_delete=models.CASCADE,
        related_name="recordings",
    )
    file_ref = models.CharField(
        max_length=512,
        help_text="Opaque storage reference for the raw audio file.",
    )
    duration_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Populated when the recording is finalized.",
    )
    sample_rate_hz = models.PositiveIntegerField(null=True, blank=True)
    channels = models.PositiveSmallIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"Recording(session={self.session_id}, ref={self.file_ref[:32]}…)"


# ---------------------------------------------------------------------------
# Sub-4 audio-pipeline outputs (scaffolding — sub-4 writes these later)
# ---------------------------------------------------------------------------


class AudioStem(models.Model):
    """A single source-separation stem output. sub-4 will write these via
    Demucs (or whatever the chosen separator ends up being). The
    ``separation_model_ref`` opaque string lets us A/B-compare different
    separators / model versions on the same Recording later.
    """

    recording = models.ForeignKey(
        Recording,
        on_delete=models.CASCADE,
        related_name="stems",
    )
    stem_type = models.CharField(
        max_length=16,
        choices=StemType.choices,
    )
    file_ref = models.CharField(max_length=512)
    separation_model_ref = models.CharField(
        max_length=128,
        blank=True,
        help_text=(
            "Opaque tag identifying the separator + version that produced "
            "this stem. e.g. 'demucs-htdemucs:v4', 'spleeter:5stems'."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recording", "stem_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["recording", "stem_type", "separation_model_ref"],
                name="unique_stem_per_recording_type_model",
            ),
        ]

    def __str__(self) -> str:
        return f"AudioStem({self.stem_type}@{self.recording_id})"


class ChordDetection(models.Model):
    """A single detected chord event with confidence. sub-4 will write
    these from CREPE / madmom / chordino / Essentia output (whichever
    landed in the pipeline). The ``voicing_style_tags`` JSONField lets
    the comparator consume directly from here.
    """

    recording = models.ForeignKey(
        Recording,
        on_delete=models.CASCADE,
        related_name="chord_detections",
    )
    beat_timestamp_ms = models.PositiveIntegerField(
        help_text="Offset from recording start in milliseconds.",
    )
    detected_chord_symbol = models.CharField(max_length=32)
    confidence = models.FloatField(
        help_text="0.0–1.0 detection confidence.",
    )

    # The bridge to apps.styles.comparator.DetectedVoicing — sub-4 fills
    # voicing_style_tags by joining detected pitches against the plugin's
    # voicings.json catalog.
    voicing_style_tags = models.JSONField(
        default=list,
        blank=True,
        help_text="List[str]. Empty when sub-4 can't map the detection to known tags.",
    )

    detection_model_ref = models.CharField(
        max_length=128,
        blank=True,
        help_text="Opaque tag identifying the recognizer + version.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recording", "beat_timestamp_ms"]
        indexes = [
            models.Index(fields=["recording", "beat_timestamp_ms"]),
        ]

    def __str__(self) -> str:
        return (
            f"ChordDetection({self.detected_chord_symbol}"
            f"@{self.beat_timestamp_ms}ms:conf={self.confidence:.2f})"
        )


# ---------------------------------------------------------------------------
# Per-segment critique tie-in
# ---------------------------------------------------------------------------


class PracticeSegment(models.Model):
    """A slice of a PracticeSession the user marked for focused feedback.

    Carries an optional FK to apps.styles.Critique so the comparator's
    output is anchored to a specific recording window. sub-D's smoke
    view creates a Critique without a PracticeSegment; the production
    loop creates segments and binds Critiques to them.
    """

    session = models.ForeignKey(
        PracticeSession,
        on_delete=models.CASCADE,
        related_name="segments",
    )
    recording = models.ForeignKey(
        Recording,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="segments",
    )
    start_ms = models.PositiveIntegerField()
    end_ms = models.PositiveIntegerField()

    critique = models.ForeignKey(
        "styles.Critique",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="practice_segments",
        help_text="Optional — segments can exist before the comparator runs.",
    )
    label = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["session", "start_ms"]

    def __str__(self) -> str:
        return f"PracticeSegment({self.session_id}:{self.start_ms}-{self.end_ms}ms)"
