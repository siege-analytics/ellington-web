"""Audio pipeline models (epic #232 / first child #233).

First PR ships only ``SoundBank``. Future children add the render
task outputs, alignment results, pitch traces, and BeatCritique
rows.

Per #232 design: ``BackingTrack`` (apps.practice) gets a FK to
``SoundBank`` so we record which bank rendered each backing.
"""

from __future__ import annotations

from django.db import models


class BankFormat(models.TextChoices):
    SF2 = "sf2", "SF2"
    SF3 = "sf3", "SF3"
    DLS = "dls", "DLS"


class BankSourceApp(models.TextChoices):
    """Where the bank came from on disk.

    ``musescore`` = bundled with the MuseScore install (auto-discovered).
    ``user`` = found under ``~/Documents/MuseScore4/Soundfonts/``.
    ``system`` = found under ``/Library/Audio/Sounds/Banks/`` or similar.
    ``other`` = an env-override path the operator added.
    """

    MUSESCORE = "musescore", "MuseScore"
    USER = "user", "User"
    SYSTEM = "system", "System"
    OTHER = "other", "Other"


class SoundBank(models.Model):
    """One SoundFont/DLS bank discovered by ``scan_sound_banks``.

    Idempotency key is ``sha256`` so re-scanning the same file on the
    same machine — or a different machine with the same bank — is a
    no-op. The path is stored verbatim for operator reference but is
    NOT the identity field.
    """

    source_app = models.CharField(
        max_length=16,
        choices=BankSourceApp.choices,
        db_index=True,
        help_text="Which install the bank came from. Drives display"
        " grouping in the picker UI.",
    )
    name = models.CharField(
        max_length=255,
        help_text="Display name. Defaults to file basename; operator"
        " can override via admin.",
    )
    format = models.CharField(
        max_length=8,
        choices=BankFormat.choices,
        db_index=True,
    )
    path = models.CharField(
        max_length=1024,
        help_text="Absolute path on the machine where ``scan_sound_banks``"
        " ran. Stored verbatim for audit; NOT the identity field.",
    )
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(
        max_length=64,
        unique=True,
        help_text="Identity key. Re-scanning the same file is a no-op.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False to hide from the picker without deleting.",
    )
    scanned_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["source_app", "name"]
        indexes = [
            models.Index(
                fields=["source_app", "is_active"],
                name="soundbank_app_active_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"SoundBank({self.source_app}/{self.name})"


class VerdictChoice(models.TextChoices):
    """§10.4 verdict enum, mirroring apps.audio.contract.VerdictLiteral."""

    SATISFIES = "satisfies", "Satisfies"
    VIOLATES = "violates", "Violates"
    NEUTRAL = "neutral", "Neutral (deferred)"
    INDETERMINATE = "indeterminate", "Indeterminate (low confidence)"


class PolarityChoice(models.TextChoices):
    """§10.4 polarity enum."""

    POSITIVE = "positive", "Positive (prescribe)"
    AVOID = "avoid", "Avoid"


class AudioVerdict(models.Model):
    """Persisted per-rule per-slice verdict from the audio comparator.

    Row-per-verdict so the rule_review UI can filter by verdict /
    rule / slice without unpacking a JSON blob. Mirrors the
    apps.audio.contract.RuleVerdict dataclass shape.

    Per #250 / epic #232. Created by the analyze_recording Celery
    task (separate ticket) — this PR only defines the storage layer.
    """

    recording = models.ForeignKey(
        "practice.Recording",
        on_delete=models.CASCADE,
        related_name="audio_verdicts",
        help_text="The Recording this verdict was computed from.",
    )

    slice_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Slice ID from slicer.slices_for_song. Together with"
        " rule_id forms the unique key.",
    )
    rule_id = models.CharField(
        max_length=128,
        db_index=True,
        help_text="EngineRule.rule_id this verdict applies to. Not a"
        " FK because EngineRule rows can be deactivated; we want the"
        " verdict to survive corpus rotation.",
    )
    rule_polarity = models.CharField(
        max_length=16,
        choices=PolarityChoice.choices,
        help_text="Mirrors RuleFireResult.polarity at the time the"
        " verdict was computed.",
    )

    verdict = models.CharField(
        max_length=16,
        choices=VerdictChoice.choices,
        db_index=True,
    )

    evidence_type = models.CharField(
        max_length=32,
        db_index=True,
        help_text="Discriminator from the EvidenceUnion variant "
        "(chord_tone_membership / scale_drift / deferred / "
        "voicing_match / rhythm_attack).",
    )
    evidence_payload = models.JSONField(
        default=dict,
        help_text="The evidence variant's fields, serialized via"
        " dataclasses.asdict. Schema is the §10.5 union; the UI"
        " renders per evidence_type.",
    )

    verdict_confidence = models.FloatField(
        default=0.0,
        db_index=True,
        help_text="§10.6 composite = observation_confidence × "
        "rule_evaluability_confidence.",
    )
    rule_evaluability_confidence = models.FloatField(
        default=0.0,
        help_text="§10.6 rule-shape complexity component, separable "
        "from observation_confidence for debug.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recording", "slice_id", "rule_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recording", "slice_id", "rule_id"],
                name="audioverdict_recording_slice_rule_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["recording", "verdict"],
                name="audioverdict_rec_verdict_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"AudioVerdict(recording={self.recording_id} "
            f"slice={self.slice_id} rule={self.rule_id} "
            f"verdict={self.verdict})"
        )


__all__ = [
    "AudioVerdict",
    "BankFormat",
    "BankSourceApp",
    "PolarityChoice",
    "SoundBank",
    "VerdictChoice",
]
