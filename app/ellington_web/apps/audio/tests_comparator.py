"""Tests for apps.audio.comparator (#248)."""

from __future__ import annotations

from django.test import TestCase

from apps.audio.comparator import compare_slice
from apps.audio.contract import (
    ChordToneMembershipEvidence,
    DeferredEvidence,
    ScaleDriftEvidence,
    SliceObservation,
)
from apps.engine_rules.firing import RuleFireResult


def _make_rule(
    *,
    rule_id: str = "r-001",
    polarity: str = "positive",
    then_action: dict | None = None,
    preference: int = 1,
) -> RuleFireResult:
    return RuleFireResult(
        rule_id=rule_id,
        preference=preference,
        polarity=polarity,
        then_action=then_action or {},
        anchor="test anchor",
        source_page=None,
        matched_dimensions={},
        confidence=1.0,
        applicability_reasons=[],
    )


def _make_obs(
    *,
    slice_id: str = "s-001",
    matched: int = 0,
    total: int = 4,
    off_chord: tuple = (),
    off_scale: tuple = (),
    scale_drift: float = 0.0,
    obs_conf: float = 0.8,
) -> SliceObservation:
    return SliceObservation(
        slice_id=slice_id,
        matched_chord_tones=matched,
        total_chord_tones=total,
        off_chord_tones=off_chord,
        off_scale_tones=off_scale,
        scale_drift_semitones=scale_drift,
        alignment_confidence=obs_conf,
        pitch_extraction_confidence=obs_conf,
        observation_confidence=obs_conf,
    )


class QualityRuleTests(TestCase):
    def test_positive_polarity_all_matched_satisfies(self):
        rule = _make_rule(then_action={"chord_quality": "maj7"})
        obs = _make_obs(matched=4, total=4)
        verdicts = compare_slice([rule], obs)
        self.assertEqual(len(verdicts), 1)
        v = verdicts[0]
        self.assertEqual(v.verdict, "satisfies")
        self.assertIsInstance(v.evidence, ChordToneMembershipEvidence)
        self.assertEqual(v.rule_evaluability_confidence, 1.0)

    def test_positive_polarity_partial_match_violates(self):
        rule = _make_rule(then_action={"chord_quality": "maj7"})
        obs = _make_obs(matched=1, total=4)
        verdicts = compare_slice([rule], obs)
        self.assertEqual(verdicts[0].verdict, "violates")

    def test_avoid_polarity_did_not_play_satisfies(self):
        """avoid + not-played = satisfies. matched_chord_tones=0 with
        no off-chord = player correctly avoided the prescribed thing."""
        rule = _make_rule(
            polarity="avoid", then_action={"chord_quality": "5"},
        )
        obs = _make_obs(matched=0, total=0)  # didn't play the 5
        verdicts = compare_slice([rule], obs)
        # In the avoid case, satisfied=False ("they didn't play it")
        # → verdict = "satisfies" per §10.4
        self.assertEqual(verdicts[0].verdict, "satisfies")

    def test_avoid_polarity_played_it_violates(self):
        rule = _make_rule(
            polarity="avoid", then_action={"chord_quality": "5"},
        )
        # User hit the chord tones — for avoid-polarity this is bad
        obs = _make_obs(matched=4, total=4)
        verdicts = compare_slice([rule], obs)
        self.assertEqual(verdicts[0].verdict, "violates")


class ScaleDriftRuleTests(TestCase):
    def test_low_drift_positive_satisfies(self):
        rule = _make_rule(
            then_action={"scale_tones": ["1", "3", "5"]},
        )
        obs = _make_obs(scale_drift=0.1)
        verdicts = compare_slice([rule], obs)
        self.assertEqual(verdicts[0].verdict, "satisfies")
        self.assertIsInstance(verdicts[0].evidence, ScaleDriftEvidence)

    def test_high_drift_positive_violates(self):
        rule = _make_rule(then_action={"scale_tones": ["1", "3", "5"]})
        obs = _make_obs(scale_drift=1.2)
        verdicts = compare_slice([rule], obs)
        self.assertEqual(verdicts[0].verdict, "violates")


class DeferralTests(TestCase):
    def test_voicing_rule_deferred(self):
        rule = _make_rule(
            then_action={"voicing": "shell_137", "voicing_family": "shell"},
        )
        obs = _make_obs(matched=4, total=4)
        verdicts = compare_slice([rule], obs)
        self.assertEqual(verdicts[0].verdict, "neutral")
        self.assertIsInstance(verdicts[0].evidence, DeferredEvidence)
        self.assertEqual(verdicts[0].evidence.deferred_until_version, "v0.2")
        self.assertIn("voicing", verdicts[0].evidence.reason)
        self.assertEqual(verdicts[0].rule_evaluability_confidence, 0.0)

    def test_rhythm_rule_deferred(self):
        rule = _make_rule(then_action={"rhythm": "1-and-3"})
        verdicts = compare_slice([rule], _make_obs())
        self.assertEqual(verdicts[0].verdict, "neutral")
        self.assertIn("rhythm", verdicts[0].evidence.reason)

    def test_unknown_shape_deferred_with_generic_reason(self):
        rule = _make_rule(then_action={"some_future_field": "x"})
        verdicts = compare_slice([rule], _make_obs())
        self.assertEqual(verdicts[0].verdict, "neutral")
        self.assertIn("no v0.1 evaluator", verdicts[0].evidence.reason)


class ConfidenceTests(TestCase):
    def test_low_observation_confidence_renders_indeterminate(self):
        rule = _make_rule(then_action={"chord_quality": "maj7"})
        obs = _make_obs(matched=4, total=4, obs_conf=0.2)
        verdicts = compare_slice([rule], obs)
        self.assertEqual(verdicts[0].verdict, "indeterminate")

    def test_verdict_confidence_is_obs_times_evaluability(self):
        rule = _make_rule(then_action={"chord_quality": "maj7"})
        obs = _make_obs(matched=4, total=4, obs_conf=0.7)
        verdicts = compare_slice([rule], obs)
        # composite = 0.7 × 1.0 = 0.7
        self.assertAlmostEqual(verdicts[0].verdict_confidence, 0.7, places=2)

    def test_deferred_verdict_has_zero_evaluability(self):
        rule = _make_rule(then_action={"voicing": "shell"})
        obs = _make_obs(obs_conf=0.9)
        verdicts = compare_slice([rule], obs)
        self.assertEqual(verdicts[0].rule_evaluability_confidence, 0.0)
        # composite = 0.9 × 0.0 = 0
        self.assertEqual(verdicts[0].verdict_confidence, 0.0)


class EdgeCases(TestCase):
    def test_empty_rule_fires_returns_empty(self):
        verdicts = compare_slice([], _make_obs())
        self.assertEqual(verdicts, [])

    def test_multiple_rules_each_get_a_verdict(self):
        r1 = _make_rule(rule_id="r-1", then_action={"chord_quality": "maj7"})
        r2 = _make_rule(rule_id="r-2", then_action={"voicing": "shell"})
        r3 = _make_rule(rule_id="r-3", then_action={"scale_tones": [1, 3]})
        verdicts = compare_slice([r1, r2, r3], _make_obs(matched=4, total=4))
        self.assertEqual([v.rule_id for v in verdicts], ["r-1", "r-2", "r-3"])
        self.assertEqual(verdicts[0].verdict, "satisfies")
        self.assertEqual(verdicts[1].verdict, "neutral")  # deferred
        self.assertEqual(verdicts[2].verdict, "satisfies")  # 0 drift
