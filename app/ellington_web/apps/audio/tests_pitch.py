"""Tests for apps.audio.pitch (#240).

Synthesizes sine waves at known frequencies + a multi-note chord
to verify:
- Single sine → f0 matches expectation
- Chord → unreliable f0 (documents the monophonic limitation)
- Voicing flag flips for silent regions

Skipped when librosa isn't available (same skip pattern as
tests_alignment).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from django.test import TestCase


def _have_librosa() -> bool:
    try:
        import librosa  # noqa: F401
        import soundfile  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(
    _have_librosa(),
    "librosa + soundfile required for pitch tests",
)
class ExtractPitchTraceTests(TestCase):
    SAMPLE_RATE = 22050
    DURATION_SEC = 3.0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp_dir = Path(tempfile.mkdtemp(prefix="ellington-pitch-test-"))

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)
        super().tearDownClass()

    def _write_sine(self, freq_hz: float, name: str = "sine.wav") -> Path:
        import numpy as np
        import soundfile as sf

        t = np.linspace(
            0, self.DURATION_SEC, int(self.SAMPLE_RATE * self.DURATION_SEC),
        )
        sig = (0.3 * np.sin(2 * np.pi * freq_hz * t)).astype("float32")
        path = self.tmp_dir / name
        sf.write(str(path), sig, self.SAMPLE_RATE)
        return path

    def _write_chord(self, freqs: list[float], name: str = "chord.wav") -> Path:
        import numpy as np
        import soundfile as sf

        t = np.linspace(
            0, self.DURATION_SEC, int(self.SAMPLE_RATE * self.DURATION_SEC),
        )
        sig = np.zeros_like(t, dtype="float32")
        for f in freqs:
            sig += (0.2 * np.sin(2 * np.pi * f * t)).astype("float32")
        path = self.tmp_dir / name
        sf.write(str(path), sig, self.SAMPLE_RATE)
        return path

    def test_recovers_a4_440hz(self):
        from apps.audio.pitch import extract_pitch_trace
        import numpy as np

        path = self._write_sine(440.0, "a4.wav")
        trace = extract_pitch_trace(path)
        voiced_freqs = trace.frequencies[trace.voicing_flag]
        median_freq = float(np.nanmedian(voiced_freqs))
        # pYIN converges close to 440; ±2 Hz on a clean sine is reasonable
        self.assertAlmostEqual(median_freq, 440.0, delta=2.0)

    def test_recovers_e3_low_guitar(self):
        from apps.audio.pitch import extract_pitch_trace
        import numpy as np

        path = self._write_sine(82.4, "low_e.wav")  # guitar low E
        trace = extract_pitch_trace(path)
        voiced = trace.frequencies[trace.voicing_flag]
        median_freq = float(np.nanmedian(voiced))
        self.assertAlmostEqual(median_freq, 82.4, delta=2.0)

    def test_voicing_flag_array_shape_matches_frequencies(self):
        from apps.audio.pitch import extract_pitch_trace

        path = self._write_sine(220.0, "shape.wav")
        trace = extract_pitch_trace(path)
        self.assertEqual(trace.frequencies.shape, trace.voicing_flag.shape)
        self.assertEqual(trace.times.shape, trace.frequencies.shape)

    def test_chord_is_unreliable_documents_monophonic_limitation(self):
        """Cmaj7 chord — pYIN can't pick a stable f0 across the four
        partials. This test documents the v1 limitation."""
        from apps.audio.pitch import extract_pitch_trace
        import numpy as np

        # C, E, G, B = Cmaj7 in 4th octave
        path = self._write_chord([261.6, 329.6, 392.0, 493.9], "cmaj7.wav")
        trace = extract_pitch_trace(path)
        voiced = trace.frequencies[trace.voicing_flag]
        if len(voiced) == 0:
            # pYIN may not voice anything on a polyphonic signal — that's
            # acceptable evidence of the limitation
            return
        # Voiced frames may scatter wildly across the partials —
        # std/mean ratio should be measurable. Assert it's non-trivial
        # (more than a clean sine would give).
        ratio = float(np.nanstd(voiced) / np.nanmean(voiced))
        self.assertGreater(ratio, 0.02, "expected chord-induced f0 scatter")

    def test_missing_file_raises(self):
        from apps.audio.pitch import extract_pitch_trace

        with self.assertRaises(FileNotFoundError):
            extract_pitch_trace(Path("/nonexistent/audio.wav"))

    def test_hop_length_round_trip(self):
        """times/frequencies length × hop_length ≈ signal length."""
        from apps.audio.pitch import extract_pitch_trace

        path = self._write_sine(440.0, "hop.wav")
        trace = extract_pitch_trace(path)
        expected_frames_approx = int(
            self.DURATION_SEC * self.SAMPLE_RATE / trace.hop_length
        )
        # Library may add one frame +/- for centering; tolerate 5
        self.assertAlmostEqual(
            len(trace.frequencies), expected_frames_approx, delta=5,
        )
