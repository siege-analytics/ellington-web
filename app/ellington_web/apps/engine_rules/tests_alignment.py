"""Tests for apps.engine_rules.alignment (#184).

Fixture-driven: synthesized detection transcripts against small chart
fixtures verify the alignment math + match-kind classification. No
audio dependency.
"""

from __future__ import annotations

from unittest import TestCase

from apps.engine_rules.alignment import (
    AlignedSlice,
    DetectedChord,
    align_detections,
)
from apps.engine_rules.firing import Slice, augment


def _slice(chord: str, beat: float = 1.0, time_sig: str = "4/4") -> Slice:
    return augment(Slice(
        target_chord_canonical=chord,
        beat_in_measure=beat,
        time_signature=time_sig,
    ))


class SliceTimeRangeTests(TestCase):
    """Verify the per-slice expected time-range arithmetic."""

    def test_two_chords_in_one_4_4_measure_at_120_bpm(self):
        # 120 bpm → 0.5 s/beat. Chord at beat 1 sounds 2 beats (1.0 s),
        # chord at beat 3 sounds the remaining 2 beats.
        slices = [
            _slice("Cmaj7", beat=1.0),
            _slice("G7", beat=3.0),
        ]
        # Send empty detections — we just want to check the windows
        aligned = align_detections([], slices, tempo_bpm=120.0)
        self.assertAlmostEqual(aligned[0].expected_start_s, 0.0)
        self.assertAlmostEqual(aligned[0].expected_end_s, 1.0)
        self.assertAlmostEqual(aligned[1].expected_start_s, 1.0)
        self.assertAlmostEqual(aligned[1].expected_end_s, 3.0)

    def test_cross_measure_boundary(self):
        # Chord at beat 3 of one measure, next chord at beat 1 of next
        # measure → 2 beats in current + 0 = 2 beats total. At 120bpm,
        # 1.0 s.
        slices = [
            _slice("Cmaj7", beat=3.0),
            _slice("G7", beat=1.0),
            _slice("Cmaj7", beat=3.0),  # so the middle slice has a "next"
        ]
        aligned = align_detections([], slices, tempo_bpm=120.0)
        self.assertAlmostEqual(aligned[0].expected_start_s, 0.0)
        self.assertAlmostEqual(aligned[0].expected_end_s, 1.0)
        self.assertAlmostEqual(aligned[1].expected_start_s, 1.0)
        self.assertAlmostEqual(aligned[1].expected_end_s, 2.0)

    def test_3_4_time_signature(self):
        # 90 bpm waltz: chord at beat 1 sounds for 3 beats (2 s).
        slices = [_slice("Em", beat=1.0, time_sig="3/4")]
        aligned = align_detections([], slices, tempo_bpm=90.0)
        seconds_per_beat = 60.0 / 90.0
        # last slice: fills the rest of the measure (3 beats from beat 1)
        self.assertAlmostEqual(
            aligned[0].expected_end_s, 3.0 * seconds_per_beat, places=4,
        )


class MatchKindClassificationTests(TestCase):

    def test_exact_quality_match(self):
        slices = [_slice("G7")]
        detections = [DetectedChord(0.0, 2.0, "G7", confidence=1.0)]
        aligned = align_detections(detections, slices, tempo_bpm=120.0)
        self.assertEqual(aligned[0].match_kind, "exact")
        self.assertEqual(aligned[0].confidence, 1.0)

    def test_family_match_when_extension_differs(self):
        # Slice expects dom7 (G7); detected is dom7b9 (G7b9) — same
        # root + family (dom7 family parent), specific differs.
        slices = [_slice("G7")]
        detections = [DetectedChord(0.0, 2.0, "G7b9", confidence=1.0)]
        aligned = align_detections(detections, slices, tempo_bpm=120.0)
        self.assertEqual(aligned[0].match_kind, "family")

    def test_quality_family_match_requires_same_root(self):
        # Slice expects G7 (dom family); detected is C7 (also dom
        # family) but DIFFERENT ROOT → "none". Alignment is per-chord,
        # not per-quality.
        slices = [_slice("G7")]
        detections = [DetectedChord(0.0, 2.0, "C7", confidence=1.0)]
        aligned = align_detections(detections, slices, tempo_bpm=120.0)
        self.assertEqual(aligned[0].match_kind, "none")

    def test_none_when_quality_unrelated(self):
        slices = [_slice("G7")]
        detections = [DetectedChord(0.0, 2.0, "Em", confidence=1.0)]
        aligned = align_detections(detections, slices, tempo_bpm=120.0)
        self.assertEqual(aligned[0].match_kind, "none")

    def test_none_when_no_detection_overlaps(self):
        slices = [_slice("G7")]
        # Detection lives in 10..15 s; slice's window is 0..2 s.
        detections = [DetectedChord(10.0, 15.0, "G7", confidence=1.0)]
        aligned = align_detections(detections, slices, tempo_bpm=120.0)
        self.assertEqual(aligned[0].match_kind, "none")
        self.assertIsNone(aligned[0].detected)
        self.assertEqual(aligned[0].confidence, 0.0)


class OverlapBasedConfidenceTests(TestCase):

    def test_partial_overlap_scales_confidence(self):
        # Slice window: 0..2 s. Detection: 0..1 s = 50% overlap.
        slices = [_slice("G7")]
        detections = [DetectedChord(0.0, 1.0, "G7", confidence=1.0)]
        aligned = align_detections(detections, slices, tempo_bpm=120.0)
        # Slice has 2 beats × 0.5s/beat = 1.0 s window (last slice
        # fills the measure remainder). Detection fills 1.0 s of that,
        # so overlap_fraction = 1.0; confidence = 1.0.
        # (Not 0.5 because last slice's beat 1 in a 4/4 fills to beat 5
        # which is 4 beats = 2 s. Detection is 0..1 = 50% = conf 0.5.)
        self.assertAlmostEqual(aligned[0].confidence, 0.5, places=3)

    def test_picks_detection_with_max_overlap(self):
        slices = [_slice("G7")]
        # Slice window: 0..2 s. Two detections; the one with bigger
        # overlap wins.
        detections = [
            DetectedChord(0.0, 0.3, "Cm", confidence=1.0),    # tiny overlap
            DetectedChord(0.5, 1.8, "G7", confidence=1.0),    # bigger overlap
        ]
        aligned = align_detections(detections, slices, tempo_bpm=120.0)
        self.assertEqual(aligned[0].detected.chord_symbol, "G7")
        self.assertEqual(aligned[0].match_kind, "exact")


class IntegrationWithSlicerStreamTests(TestCase):
    """End-to-end: realistic ii-V-I + detection transcript."""

    def test_ii_v_i_with_perfect_detection(self):
        # ii-V-I in C, 4/4 at 120bpm. Two chords per measure (1.0 s each).
        slices = [
            _slice("Dm7", beat=1.0),
            _slice("G7", beat=3.0),
            _slice("Cmaj7", beat=1.0),
        ]
        detections = [
            DetectedChord(0.0, 1.0, "Dm7", confidence=0.9),
            DetectedChord(1.0, 2.0, "G7", confidence=0.95),
            DetectedChord(2.0, 4.0, "Cmaj7", confidence=0.85),
        ]
        aligned = align_detections(detections, slices, tempo_bpm=120.0)
        self.assertEqual([a.match_kind for a in aligned], ["exact", "exact", "exact"])
        self.assertAlmostEqual(aligned[0].confidence, 0.9, places=2)
        self.assertAlmostEqual(aligned[1].confidence, 0.95, places=2)
        # Last slice expected window is 2..4 s (rest of measure); the
        # detection covers it fully → 0.85 confidence.
        self.assertAlmostEqual(aligned[2].confidence, 0.85, places=2)

    def test_player_misplayed_one_chord_wrong_root(self):
        # Player hit Bm7 instead of Dm7. Different ROOT → not a match
        # even though both are min7 by quality. Alignment cares about
        # whether the chart's chord was honored, not whether some
        # min7 chord was played.
        slices = [
            _slice("Dm7", beat=1.0),
            _slice("G7", beat=3.0),
            _slice("Cmaj7", beat=1.0),
        ]
        detections = [
            DetectedChord(0.0, 1.0, "Bm7", confidence=0.9),
            DetectedChord(1.0, 2.0, "G7", confidence=0.95),
            DetectedChord(2.0, 4.0, "Cmaj7", confidence=0.85),
        ]
        aligned = align_detections(detections, slices, tempo_bpm=120.0)
        self.assertEqual(aligned[0].match_kind, "none")
        self.assertEqual(aligned[1].match_kind, "exact")
        self.assertEqual(aligned[2].match_kind, "exact")

    def test_same_root_extension_substitution_is_family(self):
        # Slice expects Dm7; player adds a 9 → Dm9. Same root + same
        # min family → "family" match (acceptable extension).
        slices = [_slice("Dm7", beat=1.0)]
        detections = [DetectedChord(0.0, 1.0, "Dm9", confidence=0.9)]
        aligned = align_detections(detections, slices, tempo_bpm=120.0)
        self.assertEqual(aligned[0].match_kind, "family")

    def test_same_root_unrelated_quality_is_none(self):
        # Slice expects Dm7 (minor); player hits Dmaj7 (major).
        # Same root, but unrelated family → "none".
        slices = [_slice("Dm7", beat=1.0)]
        detections = [DetectedChord(0.0, 1.0, "Dmaj7", confidence=0.9)]
        aligned = align_detections(detections, slices, tempo_bpm=120.0)
        self.assertEqual(aligned[0].match_kind, "none")


class EmptyInputTests(TestCase):

    def test_no_slices_yields_no_aligned(self):
        self.assertEqual(align_detections([], [], tempo_bpm=120.0), [])

    def test_no_detections_yields_none_match_per_slice(self):
        slices = [_slice("Cmaj7"), _slice("G7", beat=3.0)]
        aligned = align_detections([], slices, tempo_bpm=120.0)
        for entry in aligned:
            self.assertEqual(entry.match_kind, "none")
            self.assertIsNone(entry.detected)
            self.assertEqual(entry.confidence, 0.0)
