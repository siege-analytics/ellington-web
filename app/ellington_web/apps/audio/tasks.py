"""Celery tasks for the audio pipeline (#235).

First task: ``render_backing`` — produces a deterministic backing
WAV for a Song using MuseScore CLI.

Per epic #232 design:
1. Generate MusicXML from the Song (via apps.audio.musicxml)
2. Write MusicXML to a tempfile
3. Invoke mscore CLI with the SoundBank's path
4. Content-address the output WAV under MEDIA_ROOT/backings/
5. update_or_create BackingTrack row keyed on
   (song, bank, tempo_bpm, key)

The MuseScore binary is already shipped in the worker image (Phase
4-MS uses ``mscore`` for the .mscz round-trip).
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from celery import shared_task

from apps.audio.models import SoundBank
from apps.audio.musicxml import song_to_musicxml
from apps.audio.storage import store_rendered_backing
from apps.charts.models import Song
from apps.practice.models import BackingTrack


log = logging.getLogger(__name__)


MSCORE_BIN_DEFAULT = "mscore"
RENDER_TIMEOUT_SECONDS = 300  # 5 min — bounds runaway renders


class RenderFailure(RuntimeError):
    """Raised when the MuseScore CLI exits non-zero."""


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def render_backing(
    self,
    song_id: int,
    bank_id: int,
    tempo_bpm: int | None = None,
    key: str | None = None,
) -> int:
    """Render a backing WAV for a Song + SoundBank → BackingTrack pk.

    Idempotent on (song, bank, tempo_bpm, key): re-running with the
    same args reuses the existing BackingTrack row. Content-addressed
    storage means re-rendering produces the same file_ref.
    """
    song = Song.objects.get(pk=song_id)
    bank = SoundBank.objects.get(pk=bank_id)

    effective_tempo = tempo_bpm or song.default_tempo_bpm
    effective_key = key or song.key or ""

    # Idempotency shortcut: if a BackingTrack already exists for these
    # exact inputs, return it without re-rendering.
    existing = BackingTrack.objects.filter(
        song=song,
        bank=bank,
        tempo_bpm=effective_tempo,
        key=effective_key,
    ).first()
    if existing is not None:
        return existing.pk

    musicxml = song_to_musicxml(
        song, tempo_bpm=effective_tempo, key=effective_key or None,
    )

    with tempfile.TemporaryDirectory(prefix="ellington-render-") as tmp_dir:
        tmp = Path(tmp_dir)
        xml_path = tmp / "in.musicxml"
        xml_path.write_text(musicxml, encoding="utf-8")
        wav_path = tmp / "out.wav"

        from django.conf import settings
        bin_path = getattr(settings, "MSCORE_BINARY", MSCORE_BIN_DEFAULT)

        cmd = [
            bin_path,
            "-o", str(wav_path),
            str(xml_path),
            "-s", bank.path,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=RENDER_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderFailure(
                f"MuseScore render timed out after {RENDER_TIMEOUT_SECONDS}s "
                f"for song={song.slug} bank={bank.name}"
            ) from exc

        if result.returncode != 0 or not wav_path.exists():
            raise RenderFailure(
                f"MuseScore render failed (rc={result.returncode}) "
                f"for song={song.slug} bank={bank.name}: "
                f"stderr={result.stderr[:512]!r}"
            )

        stored = store_rendered_backing(wav_path)

    backing, _ = BackingTrack.objects.update_or_create(
        song=song,
        bank=bank,
        tempo_bpm=effective_tempo,
        key=effective_key,
        defaults={
            "slug": f"{song.slug}-{bank.sha256[:8]}-{effective_tempo or 'auto'}",
            "title": f"{song.title} (rendered via {bank.name})",
            "audio_ref": stored.file_ref,
            "time_signature": song.time_signature or "4/4",
        },
    )
    return backing.pk
