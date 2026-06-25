"""Tests for apps.audio.alignment (#239).

Strategy: synthesize a chord-progression-like sine signal as
"canonical backing"; produce a "user recording" that's the same
signal with: (a) zero offset, (b) +2.0s offset, (c) -1.5s offset,
(d) phone-quality noise added. Verify the alignment recovers each
offset within tolerance.

Skipped when librosa isn't installed (CI handles this; tests pass
locally only when librosa is on the path).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from django.test import TestCase


def _have_librosa() -> bool:
    try:
        import librosa  # noqa: F401
        import scipy.signal  # noqa: F401
        import soundfile  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(
    _have_librosa(),
    "librosa + scipy + soundfile required for alignment tests",
)
class AlignRecordingTests(TestCase):
    """End-to-end correlation against synthesized signals."""

    SAMPLE_RATE = 22050
    DURATION_SEC = 8.0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp_dir = Path(tempfile.mkdtemp(prefix="ellington-align-test-"))

        import numpy as np
        import soundfile as sf

        t = np.linspace(0, cls.DURATION_SEC, int(cls.SAMPLE_RATE * cls.DURATION_SEC))
        # A 3-note chord ascending pattern — covers the bandpass range
        signal = (
            np.sin(2 * np.pi * 220 * t)  # A3
            + 0.6 * np.sin(2 * np.pi * 330 * t)  # E4
            + 0.4 * np.sin(2 * np.pi * 440 * t)  # A4
        ).astype("float32") * 0.3

        cls.canonical_path = cls.tmp_dir / "canonical.wav"
        sf.write(str(cls.canonical_path), signal, cls.SAMPLE_RATE)

        cls.canonical_signal = signal

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)
        super().tearDownClass()

    def _write_shifted(self, offset_sec: float, *, add_noise: bool = False) -> Path:
        """Produce a 'user recording' = canonical + offset (+optional noise)."""
        import numpy as np
        import soundfile as sf

        n = int(abs(offset_sec) * self.SAMPLE_RATE)
        canonical = self.canonical_signal
        if offset_sec >= 0:
            # User started later — pad zeros at the front
            shifted = np.concatenate([np.zeros(n, dtype="float32"), canonical])
        else:
            # User started earlier — drop n samples from the front
            shifted = canonical[n:]
        if add_noise:
            rng = np.random.default_rng(seed=42)
            noise = rng.normal(0, 0.05, size=len(shifted)).astype("float32")
            shifted = shifted + noise
        path = self.tmp_dir / f"user_{offset_sec:+.2f}.wav"
        sf.write(str(path), shifted, self.SAMPLE_RATE)
        return path

    def test_aligned_signal_offset_near_zero(self):
        from apps.audio.alignment import align_recording

        user = self._write_shifted(0.0)
        result = align_recording(user, self.canonical_path)
        self.assertAlmostEqual(result.offset_seconds, 0.0, delta=0.05)
        self.assertGreater(result.confidence, 0.3)

    def test_positive_offset_recovered(self):
        from apps.audio.alignment import align_recording

        user = self._write_shifted(+2.0)
        result = align_recording(user, self.canonical_path)
        self.assertAlmostEqual(result.offset_seconds, 2.0, delta=0.05)
        self.assertGreater(result.confidence, 0.3)

    def test_negative_offset_recovered(self):
        from apps.audio.alignment import align_recording

        user = self._write_shifted(-1.5)
        result = align_recording(user, self.canonical_path)
        # User started 1.5s before canonical → offset is -1.5
        self.assertAlmostEqual(result.offset_seconds, -1.5, delta=0.05)

    def test_with_phone_noise_still_aligns(self):
        from apps.audio.alignment import align_recording

        user = self._write_shifted(+1.0, add_noise=True)
        result = align_recording(user, self.canonical_path)
        # Tolerance widens because noise can shift the cross-corr peak slightly
        self.assertAlmostEqual(result.offset_seconds, 1.0, delta=0.1)

    def test_missing_canonical_raises(self):
        from apps.audio.alignment import align_recording

        with self.assertRaises(FileNotFoundError):
            align_recording(
                self.canonical_path,
                Path("/nonexistent/canonical.wav"),
            )

    def test_default_tempo_drift_is_one(self):
        """v1 contract: tempo_drift_ratio is always 1.0 (deferred)."""
        from apps.audio.alignment import align_recording

        user = self._write_shifted(0.0)
        result = align_recording(user, self.canonical_path)
        self.assertEqual(result.tempo_drift_ratio, 1.0)
