"""Pitch extraction — pYIN v1 (#240).

Monophonic pitch tracking via librosa's pYIN implementation. Returns
a per-frame fundamental frequency estimate plus a voicing flag so
consumers can distinguish silence / noise from notes.

Known limitation
----------------

pYIN is **monophonic**. Chord-melody material (Joe Pass, Van Eps —
the canonical heroes per the user-memory) produces unreliable f0
estimates because multiple notes sound simultaneously. v1 ships
with this limitation documented; v2 upgrade path is
`basic_pitch`_ (Spotify, MIT-licensed, polyphonic note detection,
adds a TensorFlow dep — deferred until we have a recording corpus
to validate the cost/benefit on).

.. _basic_pitch: https://github.com/spotify/basic-pitch

Per child #240 of #232.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True)
class PitchTrace:
    """Per-frame pitch trace from :func:`extract_pitch_trace`.

    Attributes:
        times: 1-D numpy array of frame center times (seconds).
        frequencies: 1-D numpy array of estimated f0 in Hz. ``NaN``
          on frames flagged unvoiced.
        voicing_flag: 1-D bool array — True where pYIN judged the
          frame to carry a pitch.
        sample_rate: SR audio was loaded at (post-resample).
        hop_length: Hop length in samples between frame centers.
    """

    times: "np.ndarray"
    frequencies: "np.ndarray"
    voicing_flag: "np.ndarray"
    sample_rate: int
    hop_length: int


# Default pYIN parameters tuned for guitar:
# - fmin 80 Hz covers low-E (82 Hz)
# - fmax 1500 Hz covers up to ~F#6 — high enough for chord-melody top
# - frame_length 2048 / hop_length 512 @ 22050 Hz = ~23 ms hops
_DEFAULT_SR = 22050
_DEFAULT_FMIN = 80.0
_DEFAULT_FMAX = 1500.0
_DEFAULT_FRAME_LENGTH = 2048
_DEFAULT_HOP_LENGTH = 512


def extract_pitch_trace(
    audio_path: Path,
    *,
    sample_rate: int = _DEFAULT_SR,
    fmin: float = _DEFAULT_FMIN,
    fmax: float = _DEFAULT_FMAX,
    frame_length: int = _DEFAULT_FRAME_LENGTH,
    hop_length: int = _DEFAULT_HOP_LENGTH,
) -> PitchTrace:
    """Extract a pitch trace from one audio file via librosa's pYIN.

    Args:
        audio_path: WAV / MP3 / M4A / FLAC — librosa decodes most
          common formats.
        sample_rate: Resample target. 22050 Hz is the librosa
          default and is plenty for f0 < 1500 Hz.
        fmin / fmax: Search range in Hz. Defaults cover the guitar's
          useful range.
        frame_length / hop_length: pYIN window parameters. Defaults
          give ~23 ms hops at 22050 Hz — fine-enough resolution for
          per-beat analysis at jazz tempos.

    Returns:
        :class:`PitchTrace`. The consumer aligns the frame times
        with the slice/beat timeline (after :func:`apps.audio.alignment.align_recording`
        applies its offset).

    Raises:
        FileNotFoundError if the audio file is missing.
    """
    # Lazy imports so importing apps.audio.pitch doesn't pay the
    # librosa/numpy cost unless an analysis is actually running.
    import librosa
    import numpy as np

    if not audio_path.exists():
        raise FileNotFoundError(f"audio not found: {audio_path}")

    signal, sr = librosa.load(str(audio_path), sr=sample_rate, mono=True)

    f0, voiced_flag, voiced_prob = librosa.pyin(
        signal,
        fmin=fmin,
        fmax=fmax,
        sr=sr,
        frame_length=frame_length,
        hop_length=hop_length,
    )

    # frame center times — librosa convention: frame i is centered at
    # i * hop_length / sr.
    times = librosa.frames_to_time(
        np.arange(len(f0)), sr=sr, hop_length=hop_length,
    )

    return PitchTrace(
        times=times,
        frequencies=f0,
        voicing_flag=voiced_flag.astype(bool),
        sample_rate=sr,
        hop_length=hop_length,
    )
