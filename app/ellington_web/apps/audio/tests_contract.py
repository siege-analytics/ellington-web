"""Tests for apps.audio.contract — Conformance Verdict Contract (#246).

These tests verify the dataclass shape matches firing-spec §10 by
construction (field set, hashability, frozen invariant). A follow-up
will add a doc-grep test that opens the canonical spec file and
asserts each field name appears in the §10 prose.
"""

from __future__ import annotations

from dataclasses import asdict

from django.test import TestCase

from apps.audio.contract import (
    ChordToneMembershipEvidence,
    DeferredEvidence,
    EvidenceUnion,
    PlayedPitch,
    RhythmAttackEvidence,
    RuleVerdict,
    ScaleDriftEvidence,
    SliceObservation,
    VoicingMatchEvidence,
)


class SliceObservationShapeTests(TestCase):
    """Field set + frozen invariant."""

    def test_minimal_construction(self):
        obs = SliceObservation(slice_id="s-001")
        self.assertEqual(obs.slice_id, "s-001")
        self.assertEqual(obs.played_pitches, ())
        self.assertEqual(obs.matched_chord_tones, 0)
        self.assertIsNone(obs.inferred_chord_quality)

    def test_full_construction(self):
        obs = SliceObservation(
            slice_id="s-002",
            played_pitches=(
                PlayedPitch(pitch_name="C4", duration_s=0.5, confidence=0.9),
                PlayedPitch(pitch_name="E4", duration_s=0.4, confidence=0.8),
            ),
            played_intervals_relative_to_root=(0, 4),
            inferred_chord_quality=None,
            matched_chord_tones=2,
            total_chord_tones=4,
            off_chord_tones=("F#4",),
            off_scale_tones=("Ab4",),
            scale_drift_semitones=0.3,
            alignment_confidence=0.85,
            pitch_extraction_confidence=0.72,
            observation_confidence=0.78,
        )
        self.assertEqual(len(obs.played_pitches), 2)
        self.assertEqual(obs.matched_chord_tones, 2)
        self.assertEqual(obs.off_chord_tones, ("F#4",))

    def test_frozen_invariant(self):
        obs = SliceObservation(slice_id="s-003")
        with self.assertRaises(Exception):
            obs.matched_chord_tones = 5  # frozen → AttributeError

    def test_hashable(self):
        obs = SliceObservation(slice_id="s-004")
        # Hashable because frozen + all tuple fields
        _ = {obs: True}


class EvidenceUnionTests(TestCase):
    """Discriminated-union by `type` field."""

    def test_chord_tone_membership_variant(self):
        ev = ChordToneMembershipEvidence(
            matched=3, total=4, missing=("b7",), extra=()
        )
        self.assertEqual(ev.type, "chord_tone_membership")
        self.assertEqual(ev.missing, ("b7",))

    def test_scale_drift_variant(self):
        ev = ScaleDriftEvidence(
            median_drift_semitones=0.4,
            max_drift_semitones=0.9,
            drift_frame_count=12,
        )
        self.assertEqual(ev.type, "scale_drift")

    def test_deferred_variant(self):
        ev = DeferredEvidence(
            reason="requires polyphonic pitch",
            deferred_until_version="v0.2",
        )
        self.assertEqual(ev.type, "deferred")
        self.assertEqual(ev.reason, "requires polyphonic pitch")

    def test_v2_voicing_match_variant_present(self):
        """§10.5 reserves voicing_match for v2 — must be importable now
        so consumers don't fail-closed when v2 evidence lands."""
        ev = VoicingMatchEvidence(
            matched_shape_id="cm7-shell-1",
            expected_shape_id="cm7-shell-1",
        )
        self.assertEqual(ev.type, "voicing_match")

    def test_v2_rhythm_attack_variant_present(self):
        ev = RhythmAttackEvidence(
            expected_attack_count=4, observed_attack_count=3,
        )
        self.assertEqual(ev.type, "rhythm_attack")

    def test_round_trip_via_asdict(self):
        """asdict() captures the discriminator + payload fields."""
        ev = ChordToneMembershipEvidence(matched=2, total=4, missing=("3",))
        d = asdict(ev)
        self.assertEqual(d["type"], "chord_tone_membership")
        self.assertEqual(d["matched"], 2)
        self.assertEqual(d["missing"], ("3",))


class RuleVerdictShapeTests(TestCase):
    def test_satisfies_with_chord_tone_evidence(self):
        verdict = RuleVerdict(
            slice_id="s-005",
            rule_id="joe-pass-001",
            rule_polarity="positive",
            verdict="satisfies",
            evidence=ChordToneMembershipEvidence(matched=4, total=4),
            verdict_confidence=0.82,
            rule_evaluability_confidence=0.9,
        )
        self.assertEqual(verdict.rule_polarity, "positive")
        self.assertEqual(verdict.verdict, "satisfies")

    def test_neutral_with_deferred_evidence(self):
        verdict = RuleVerdict(
            slice_id="s-006",
            rule_id="bergonzi-voicing-001",
            rule_polarity="positive",
            verdict="neutral",
            evidence=DeferredEvidence(
                reason="requires polyphonic pitch",
                deferred_until_version="v0.2",
            ),
            verdict_confidence=0.6,
            rule_evaluability_confidence=0.0,
        )
        self.assertEqual(verdict.verdict, "neutral")
        self.assertEqual(verdict.evidence.type, "deferred")

    def test_violates_with_avoid_polarity(self):
        verdict = RuleVerdict(
            slice_id="s-007",
            rule_id="laukens-avoid-5",
            rule_polarity="avoid",
            verdict="violates",
            evidence=ChordToneMembershipEvidence(
                matched=1, total=0, extra=("5",),
            ),
            verdict_confidence=0.7,
            rule_evaluability_confidence=0.85,
        )
        self.assertEqual(verdict.rule_polarity, "avoid")

    def test_indeterminate_low_confidence(self):
        verdict = RuleVerdict(
            slice_id="s-008",
            rule_id="some-rule",
            rule_polarity="positive",
            verdict="indeterminate",
            evidence=DeferredEvidence(reason="alignment_confidence < 0.3"),
            verdict_confidence=0.15,
            rule_evaluability_confidence=0.9,
        )
        self.assertEqual(verdict.verdict, "indeterminate")

    def test_frozen_invariant(self):
        verdict = RuleVerdict(
            slice_id="s-009",
            rule_id="r",
            rule_polarity="positive",
            verdict="neutral",
            evidence=DeferredEvidence(),
        )
        with self.assertRaises(Exception):
            verdict.verdict = "satisfies"
