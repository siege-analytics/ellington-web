"""Focused tests for #265 — scale_drift_per_frame_semitones on
SliceObservation and the comparator's use of it."""

from __future__ import annotations

from django.test import TestCase

from apps.audio.comparator import _evaluate_scale_drift
from apps.audio.contract import ScaleDriftEvidence, SliceObservation


def _make_obs(*, scalar: float, per_frame: tuple[float, ...] = ()):
    return SliceObservation(
        slice_id="s1",
        scale_drift_semitones=scalar,
        scale_drift_per_frame_semitones=per_frame,
        observation_confidence=1.0,
        alignment_confidence=1.0,
        pitch_extraction_confidence=1.0,
    )


class ScaleDriftPerFrameTests(TestCase):
    def test_empty_per_frame_falls_back_to_scalar(self):
        obs = _make_obs(scalar=0.10, per_frame=())
        evidence, verdict = _evaluate_scale_drift(
            obs, polarity="avoid",
            then_action={"max_scale_drift_semitones": 0.25},
        )
        self.assertEqual(evidence.median_drift_semitones, 0.10)
        self.assertEqual(evidence.max_drift_semitones, 0.10)
        self.assertEqual(evidence.drift_frame_count, 0)
        self.assertEqual(verdict, "satisfies")

    def test_per_frame_median_max_frame_count(self):
        obs = _make_obs(
            scalar=0.04,
            per_frame=(0.02, 0.04, 0.04, 0.12),
        )
        evidence, verdict = _evaluate_scale_drift(
            obs, polarity="avoid",
            then_action={"max_scale_drift_semitones": 0.25},
        )
        # sorted [0.02, 0.04, 0.04, 0.12]; median = (0.04+0.04)/2 = 0.04
        self.assertAlmostEqual(evidence.median_drift_semitones, 0.04, places=6)
        self.assertAlmostEqual(evidence.max_drift_semitones, 0.12, places=6)
        # All below 0.25 threshold → 0 frames
        self.assertEqual(evidence.drift_frame_count, 0)
        self.assertEqual(verdict, "satisfies")

    def test_per_frame_odd_length_median(self):
        obs = _make_obs(
            scalar=0.0,
            per_frame=(0.10, 0.20, 0.30),
        )
        evidence, _ = _evaluate_scale_drift(
            obs, polarity="positive",
            then_action={"max_scale_drift_semitones": 0.5},
        )
        # median of odd-length sorted [0.10, 0.20, 0.30] = 0.20
        self.assertAlmostEqual(evidence.median_drift_semitones, 0.20, places=6)
        self.assertAlmostEqual(evidence.max_drift_semitones, 0.30, places=6)

    def test_per_frame_frame_count_against_threshold(self):
        obs = _make_obs(
            scalar=0.0,
            per_frame=(0.10, 0.30, 0.40, 0.05, 0.35),
        )
        evidence, verdict = _evaluate_scale_drift(
            obs, polarity="avoid",
            then_action={"max_scale_drift_semitones": 0.25},
        )
        # Above threshold 0.25: 0.30, 0.40, 0.35 → 3 frames
        self.assertEqual(evidence.drift_frame_count, 3)
        self.assertAlmostEqual(evidence.max_drift_semitones, 0.40, places=6)
        # Max above threshold → violates on avoid polarity (verdict is
        # polarity-invariant per #257)
        self.assertEqual(verdict, "violates")

    def test_evidence_is_scale_drift_variant(self):
        obs = _make_obs(scalar=0.0, per_frame=(0.05, 0.10))
        evidence, _ = _evaluate_scale_drift(
            obs, polarity="avoid",
        )
        self.assertIsInstance(evidence, ScaleDriftEvidence)
        self.assertEqual(evidence.type, "scale_drift")

    def test_polarity_does_not_affect_verdict(self):
        """Regression guard for the polarity-invariance fixed in #257 —
        per-frame path must not reintroduce polarity-relative flipping."""
        obs = _make_obs(scalar=0.0, per_frame=(0.05, 0.06, 0.07))
        _, verdict_pos = _evaluate_scale_drift(
            obs, polarity="positive",
            then_action={"max_scale_drift_semitones": 0.25},
        )
        _, verdict_avoid = _evaluate_scale_drift(
            obs, polarity="avoid",
            then_action={"max_scale_drift_semitones": 0.25},
        )
        self.assertEqual(verdict_pos, "satisfies")
        self.assertEqual(verdict_avoid, "satisfies")

    def test_default_threshold_when_no_then_action(self):
        obs = _make_obs(scalar=0.0, per_frame=(0.10, 0.20, 0.30))
        evidence, verdict = _evaluate_scale_drift(
            obs, polarity="avoid",
        )
        # Default threshold is 0.5 semitones per the module constant;
        # all frames below → 0 count, satisfies.
        self.assertEqual(evidence.drift_frame_count, 0)
        self.assertEqual(verdict, "satisfies")
