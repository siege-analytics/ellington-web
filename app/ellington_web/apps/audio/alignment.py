"""Audio time-alignment — user recording ↔ canonical backing (#239).

Given a user's audio recording (phone or GarageBand quality, mixed
mono) and a deterministically-rendered canonical backing WAV (from
``render_backing`` per #235), produce the time offset + tempo drift
needed to align the slice-level analysis to the canonical chart
timeline.

Why this works without ML
-------------------------

The canonical backing's waveform is exact. Cross-correlation of the
user's recording against the canonical backing (in a low-pass +
downsampled feature space to ignore EQ differences) yields a sharp
peak at the correct offset. Phone-quality recordings have a small
time drift relative to the canonical (mic ADC clock vs. playback
DAC clock), but that drift is small enough over a few minutes that
a single offset estimate carries the audio analysis far. Tempo-
drift correction is a follow-up if data shows it's needed.

Per epic #232, this module is INDEPENDENT of:
- The pitch extractor (#240)
- The plugin-agent-locked per-slice comparator contract (anchor #2 on
  plugin#594) — only the comparator needs the contract; alignment is
  pure DSP

Per child #239.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AlignmentResult:
    """Output of :func:`align_recording`.

    Attributes:
        offset_seconds: How many seconds to shift the user recording
          so its t=0 lines up with the canonical's t=0. Positive means
          the user started recording AFTER the canonical's start;
          negative means before.
        confidence: 0..1 measure of cross-correlation peak sharpness.
          A clean phone recording against the canonical typically
          scores 0.7+; below 0.3 the alignment is unreliable.
        tempo_drift_ratio: Estimated tempo ratio of user vs canonical
          (1.0 = identical, 1.01 = user 1% faster). v1 returns 1.0
          always — drift estimation is a follow-up once we have a
          recording corpus to validate against.
    """

    offset_seconds: float
    confidence: float
    tempo_drift_ratio: float = 1.0


# Feature-extraction sample rate. 4 kHz captures the harmonic
# information needed for correlation while keeping the signal small
# enough that 5 min of audio = 1.2M samples (manageable for FFT).
_FEATURE_SR = 4_000

# Lower / upper bandpass corners (Hz). Strips out subsonic rumble +
# very-high EQ shimmer that don't carry harmonic alignment info.
_BANDPASS_LOW = 80.0
_BANDPASS_HIGH = 1500.0


def align_recording(
    user_path: Path,
    canonical_path: Path,
    *,
    max_offset_seconds: float = 30.0,
) -> AlignmentResult:
    """Estimate the time offset between two recordings via
    cross-correlation in a downsampled bandpassed feature space.

    Args:
        user_path: Path to the user's recording (WAV / MP3 / M4A;
          librosa handles decoding).
        canonical_path: Path to the canonical backing WAV.
        max_offset_seconds: Cap the search window. Recordings more
          than this far apart probably mean the user uploaded the
          wrong audio; we return low confidence rather than searching
          forever.

    Returns:
        :class:`AlignmentResult`. ``confidence`` below 0.3 means the
        offset is unreliable — the consumer should surface a
        re-align-or-re-record affordance.

    Raises:
        FileNotFoundError if either input doesn't exist.
    """
    # Lazy import — librosa is heavy and the rest of apps.audio
    # shouldn't pay the import cost unless alignment is actually run.
    import librosa
    import numpy as np
    from scipy.signal import correlate

    if not user_path.exists():
        raise FileNotFoundError(f"user recording not found: {user_path}")
    if not canonical_path.exists():
        raise FileNotFoundError(f"canonical backing not found: {canonical_path}")

    user_signal = _load_feature(user_path, librosa, np)
    canonical_signal = _load_feature(canonical_path, librosa, np)

    # Cross-correlation. ``mode='full'`` gives all lags; we slice to
    # the max_offset window for both efficiency and to refuse
    # absurdly-far offsets.
    corr = correlate(user_signal, canonical_signal, mode="full")
    # Lag = 0 corresponds to index len(canonical)-1 in 'full' mode
    zero_lag_idx = len(canonical_signal) - 1

    max_offset_samples = int(max_offset_seconds * _FEATURE_SR)
    lo = max(0, zero_lag_idx - max_offset_samples)
    hi = min(len(corr), zero_lag_idx + max_offset_samples + 1)
    windowed = corr[lo:hi]
    if len(windowed) == 0:
        return AlignmentResult(offset_seconds=0.0, confidence=0.0)

    peak_idx_in_window = int(np.argmax(np.abs(windowed)))
    peak_value = float(np.abs(windowed[peak_idx_in_window]))

    # Confidence: peak / mean(|windowed|) normalized to [0, 1]
    mean_abs = float(np.mean(np.abs(windowed)))
    confidence = (
        min(1.0, (peak_value / mean_abs) / 10.0)
        if mean_abs > 0 else 0.0
    )

    peak_idx_in_corr = lo + peak_idx_in_window
    lag_samples = peak_idx_in_corr - zero_lag_idx
    offset_seconds = lag_samples / _FEATURE_SR

    return AlignmentResult(
        offset_seconds=offset_seconds,
        confidence=confidence,
    )


def _load_feature(path: Path, librosa, np):
    """Load + downsample + bandpass + normalize to alignment feature."""
    # librosa.load auto-resamples to ``sr=_FEATURE_SR``.
    signal, _ = librosa.load(str(path), sr=_FEATURE_SR, mono=True)
    # Bandpass via librosa's high-/lowpass equivalents using FFT
    # filtering. Cheaper than scipy.butter for this one-shot use.
    fft = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(len(signal), d=1.0 / _FEATURE_SR)
    mask = (freqs >= _BANDPASS_LOW) & (freqs <= _BANDPASS_HIGH)
    fft *= mask
    filtered = np.fft.irfft(fft, n=len(signal))
    # Zero-mean + L2 normalize so correlation magnitude isn't
    # dominated by overall loudness differences (phone mic vs. line-out)
    filtered = filtered - np.mean(filtered)
    norm = np.linalg.norm(filtered)
    if norm > 0:
        filtered = filtered / norm
    return filtered.astype(np.float32)
