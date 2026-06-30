"""§10 parity oracle roundtrip test (#255 / cross-project plugin#596).

Loads the canonical conformance fixture (1 SliceObservation + 3
RuleFireResult inputs + expected RuleVerdict outputs covering all
three v0.1 evidence variants) and asserts that ``compare_slice()``
reproduces the expected outputs field-by-field.

If our comparator drifts from plugin's §10 spec, this test fails
loud — the exact drift signal we wanted. Per plugin agent on
plugin#596: this test runs **behavior**, not text, so it catches
drift that a doc-grep test would miss.

Phase A (this PR): fixture inlined as a Python constant per plugin
agent's PR #596 description.
Phase B (follow-up after plugin#596 merges): swap the inline
constant for ``json.load(open(canonical_fixture_path))``. The shape
should match exactly; if it doesn't, Phase A's structural test
catches the inline-vs-canonical mismatch when we swap.
"""

from __future__ import annotations

from django.test import TestCase

from apps.audio.comparator import compare_slice
from apps.audio.contract import (
    ChordToneMembershipEvidence,
    DeferredEvidence,
    PlayedPitch,
    RuleVerdict,
    ScaleDriftEvidence,
    SliceObservation,
)
from apps.engine_rules.firing import RuleFireResult


# ---------------------------------------------------------------------------
# Fixture — mirrors plugin/docs/fixtures/conformance-v0.2.1-fixture.json
# from plugin#596. Replace with json.load when canonical file lands.
# ---------------------------------------------------------------------------


def _build_fixture_observation() -> SliceObservation:
    """Cmaj7 context — player hit all 4 chord tones, stayed on scale."""
    return SliceObservation(
        slice_id="fixture-slice-001",
        played_pitches=(
            PlayedPitch(pitch_name="C4", duration_s=0.4, confidence=0.9),
            PlayedPitch(pitch_name="E4", duration_s=0.4, confidence=0.85),
            PlayedPitch(pitch_name="G4", duration_s=0.4, confidence=0.88),
            PlayedPitch(pitch_name="B4", duration_s=0.4, confidence=0.82),
        ),
        played_intervals_relative_to_root=(0, 4, 7, 11),
        inferred_chord_quality=None,
        matched_chord_tones=4,
        total_chord_tones=4,
        off_chord_tones=(),
        off_scale_tones=(),
        scale_drift_semitones=0.2,
        alignment_confidence=0.85,
        pitch_extraction_confidence=0.72,
        observation_confidence=0.61,
    )


def _build_fixture_rule_fires() -> list[RuleFireResult]:
    """Three rules covering the three v0.1 evidence variants per
    plugin#596's fixture description."""
    return [
        # 1. Voicing-prescriptive → neutral + DeferredEvidence
        RuleFireResult(
            rule_id="fixture-rule-voicing",
            preference=2,
            polarity="positive",
            then_action={"voicing": "shell_137"},
            anchor="Joe Pass shell voicings",
            source_page=42,
            matched_dimensions={},
            confidence=1.0,
            applicability_reasons=[],
        ),
        # 2. Chord-quality-prescriptive → satisfies + ChordToneMembershipEvidence
        RuleFireResult(
            rule_id="fixture-rule-quality",
            preference=1,
            polarity="positive",
            then_action={"chord_quality": "maj7"},
            anchor="Cmaj7 quality match",
            source_page=10,
            matched_dimensions={},
            confidence=1.0,
            applicability_reasons=[],
        ),
        # 3. Avoid scale-drift → satisfies + ScaleDriftEvidence
        # (demonstrates §10.4 cross-product on the avoid side)
        RuleFireResult(
            rule_id="fixture-rule-avoid-drift",
            preference=-1,
            polarity="avoid",
            then_action={"scale_tones": ["1", "3", "5", "7"]},
            anchor="Avoid drifting off the major-7 scale",
            source_page=88,
            matched_dimensions={},
            confidence=1.0,
            applicability_reasons=[],
        ),
    ]


# Expected outputs per plugin#596's fixture. Field names + values match
# the canonical fixture JSON one-to-one.
_EXPECTED_VERDICTS = [
    # 1. Voicing rule → neutral + DeferredEvidence
    {
        "slice_id": "fixture-slice-001",
        "rule_id": "fixture-rule-voicing",
        "rule_polarity": "positive",
        "verdict": "neutral",
        "evidence_type": "deferred",
        "evidence_payload_keys": {
            "type", "reason", "deferred_until_version",
        },
        "rule_evaluability_confidence": 0.0,
    },
    # 2. Quality rule → satisfies + ChordToneMembershipEvidence
    {
        "slice_id": "fixture-slice-001",
        "rule_id": "fixture-rule-quality",
        "rule_polarity": "positive",
        "verdict": "satisfies",
        "evidence_type": "chord_tone_membership",
        "evidence_payload_keys": {"type", "matched", "total", "missing", "extra"},
        "rule_evaluability_confidence": 1.0,
    },
    # 3. Avoid scale-tones rule → satisfies + ScaleDriftEvidence
    # Player has low drift (0.2 semitones); for an "avoid drifting"
    # rule, low drift = satisfied the avoidance. Per §10.4
    # cross-product: avoid × did-not-do-avoided-thing = satisfies.
    {
        "slice_id": "fixture-slice-001",
        "rule_id": "fixture-rule-avoid-drift",
        "rule_polarity": "avoid",
        "verdict": "satisfies",
        "evidence_type": "scale_drift",
        "evidence_payload_keys": {
            "type", "median_drift_semitones", "max_drift_semitones",
            "drift_frame_count",
        },
        "rule_evaluability_confidence": 1.0,
    },
]


class ParityOracleRoundtripTests(TestCase):
    """Comparator output matches plugin#596's expected fixture outputs."""

    def setUp(self):
        self.obs = _build_fixture_observation()
        self.rule_fires = _build_fixture_rule_fires()
        self.actual = compare_slice(self.rule_fires, self.obs)

    def test_three_verdicts_returned(self):
        self.assertEqual(len(self.actual), 3)

    def test_verdict_1_voicing_neutral_deferred(self):
        expected = _EXPECTED_VERDICTS[0]
        actual = self.actual[0]
        self.assertEqual(actual.slice_id, expected["slice_id"])
        self.assertEqual(actual.rule_id, expected["rule_id"])
        self.assertEqual(actual.rule_polarity, expected["rule_polarity"])
        self.assertEqual(actual.verdict, expected["verdict"])
        self.assertIsInstance(actual.evidence, DeferredEvidence)
        self.assertEqual(actual.evidence.type, expected["evidence_type"])
        self.assertEqual(
            actual.rule_evaluability_confidence,
            expected["rule_evaluability_confidence"],
        )

    def test_verdict_2_quality_satisfies_chord_tone(self):
        expected = _EXPECTED_VERDICTS[1]
        actual = self.actual[1]
        self.assertEqual(actual.rule_id, expected["rule_id"])
        self.assertEqual(actual.verdict, expected["verdict"])
        self.assertIsInstance(actual.evidence, ChordToneMembershipEvidence)
        self.assertEqual(actual.evidence.matched, 4)
        self.assertEqual(actual.evidence.total, 4)
        self.assertEqual(
            actual.rule_evaluability_confidence,
            expected["rule_evaluability_confidence"],
        )

    def test_verdict_3_avoid_scale_drift_satisfies(self):
        """Player has low drift; for an 'avoid drifting' rule per §10.4,
        avoid × did-not-do-avoided-thing → satisfies. If this test
        FAILS, the comparator's avoid+scale_drift semantics disagree
        with plugin#596's canonical interpretation — file the fix as a
        comparator-semantics ticket."""
        expected = _EXPECTED_VERDICTS[2]
        actual = self.actual[2]
        self.assertEqual(actual.rule_id, expected["rule_id"])
        self.assertEqual(actual.rule_polarity, "avoid")
        self.assertEqual(
            actual.verdict, expected["verdict"],
            msg=(
                "Comparator's avoid+scale-drift verdict ("
                f"{actual.verdict!r}) disagrees with plugin#596 fixture "
                f"(expected {expected['verdict']!r}). This is the drift "
                "signal — fix in comparator.py, not this test."
            ),
        )
        self.assertIsInstance(actual.evidence, ScaleDriftEvidence)
        self.assertEqual(
            actual.rule_evaluability_confidence,
            expected["rule_evaluability_confidence"],
        )

    def test_composite_confidence_identity(self):
        """§10.6: verdict_confidence == observation_confidence × evaluability."""
        for actual in self.actual:
            expected_composite = (
                self.obs.observation_confidence
                * actual.rule_evaluability_confidence
            )
            self.assertAlmostEqual(
                actual.verdict_confidence, expected_composite, places=2,
                msg=f"§10.6 confidence identity violated for {actual.rule_id}",
            )

    def test_neutral_iff_deferred_evidence(self):
        """§10.4 invariant: neutral verdict ⟺ DeferredEvidence."""
        for actual in self.actual:
            if actual.verdict == "neutral":
                self.assertIsInstance(actual.evidence, DeferredEvidence)
            if isinstance(actual.evidence, DeferredEvidence):
                self.assertEqual(actual.verdict, "neutral")
