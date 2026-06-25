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


__all__ = ["BankFormat", "BankSourceApp", "SoundBank"]
