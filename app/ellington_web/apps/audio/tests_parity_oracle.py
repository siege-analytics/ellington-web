"""§10 parity oracle roundtrip test (#255 / plugin#596).

Phase B: loads the canonical conformance fixture vendored from the
firing-spec repo and asserts that ``compare_slice()`` reproduces the
expected outputs field-by-field.

Canonical fixture provenance:
- Source: plugin#596 (firing-spec engine-rules)
- Pinned at SHA: ``8f60fc8``
- Raw URL: https://raw.githubusercontent.com/siege-analytics/musescore4-chord-library-plugin/8f60fc8/docs/fixtures/conformance-v0.2.1-fixture.json
- Vendored at: app/ellington_web/apps/audio/fixtures/conformance-v0.2.1-fixture.json

If our comparator drifts from plugin's §10 spec, this test fails loud —
the exact drift signal the oracle was designed for. Per plugin agent:
"drift is loud, not silent."

Known divergences surfaced by Phase B (to be fixed in follow-up ticket):
- canonical ``then_action`` keys (``expected_chord_quality``,
  ``max_scale_drift_semitones``, ``action``) do not match what
  ``_prescribes_quality`` / ``_prescribes_scale_constraint`` look for
- ``ScaleDriftEvidence`` canonical shape has distinct
  ``median_drift_semitones`` / ``max_drift_semitones`` /
  ``drift_frame_count`` computed against the rule's threshold; our
  evaluator currently reuses ``obs.scale_drift_semitones`` 3×
"""

from __future__ import annotations

import json
from pathlib import Path

from django.test import TestCase

from apps.audio.comparator import compare_slice
from apps.audio.contract import (
    ChordToneMembershipEvidence,
    DeferredEvidence,
    PlayedPitch,
    ScaleDriftEvidence,
    SliceObservation,
)
from apps.engine_rules.firing import RuleFireResult


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "conformance-v0.2.1-fixture.json"
)
PINNED_PLUGIN_SHA = "8f60fc8"


def _load_fixture() -> dict:
    with FIXTURE_PATH.open() as f:
        return json.load(f)


def _build_observation(payload: dict) -> SliceObservation:
    return SliceObservation(
        slice_id=payload["slice_id"],
        played_pitches=tuple(
            PlayedPitch(
                pitch_name=p["pitch_name"],
                duration_s=p["duration_s"],
                confidence=p["confidence"],
            )
            for p in payload["played_pitches"]
        ),
        played_intervals_relative_to_root=tuple(
            payload["played_intervals_relative_to_root"]
        ),
        inferred_chord_quality=payload["inferred_chord_quality"],
        matched_chord_tones=payload["matched_chord_tones"],
        total_chord_tones=payload["total_chord_tones"],
        off_chord_tones=tuple(payload["off_chord_tones"]),
        off_scale_tones=tuple(payload["off_scale_tones"]),
        scale_drift_semitones=payload["scale_drift_semitones"],
        alignment_confidence=payload["alignment_confidence"],
        pitch_extraction_confidence=payload["pitch_extraction_confidence"],
        observation_confidence=payload["observation_confidence"],
    )


def _build_rule_fire(payload: dict) -> RuleFireResult:
    return RuleFireResult(
        rule_id=payload["rule_id"],
        preference=payload["preference"],
        polarity=payload["polarity"],
        then_action=payload["then_action"],
        anchor=payload["anchor"],
        source_page=payload["source_page"],
        matched_dimensions=payload["matched_dimensions"],
        confidence=payload["confidence"],
        applicability_reasons=payload["applicability_reasons"],
    )


class ParityOracleRoundtripTests(TestCase):
    """Comparator output matches plugin#596's canonical fixture."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fixture = _load_fixture()
        cls.observation = _build_observation(cls.fixture["slice_observation"])
        cls.rule_fires = [
            _build_rule_fire(entry["rule_fire_result"])
            for entry in cls.fixture["fired_rules"]
        ]
        cls.expected = [
            entry["expected_rule_verdict"]
            for entry in cls.fixture["fired_rules"]
        ]
        cls.actual = compare_slice(cls.rule_fires, cls.observation)

    def test_fixture_version_pinned(self):
        self.assertEqual(
            self.fixture["_consumer_contract_version"], "0.2.1",
            msg="Fixture contract version drifted from 0.2.1",
        )

    def test_three_verdicts_returned(self):
        self.assertEqual(len(self.actual), 3)

    def test_verdict_voicing_neutral_deferred(self):
        expected = self.expected[0]
        actual = self.actual[0]
        self.assertEqual(actual.slice_id, expected["slice_id"])
        self.assertEqual(actual.rule_id, expected["rule_id"])
        self.assertEqual(actual.rule_polarity, expected["rule_polarity"])
        self.assertEqual(actual.verdict, expected["verdict"])
        self.assertIsInstance(actual.evidence, DeferredEvidence)
        self.assertEqual(
            actual.rule_evaluability_confidence,
            expected["rule_evaluability_confidence"],
        )

    def test_verdict_quality_satisfies_chord_tone(self):
        """Canonical fixture uses ``expected_chord_quality`` key.
        Our ``_prescribes_quality`` currently looks for
        ``chord_quality`` / ``quality`` / ``quality_family`` — this
        test surfaces the key-name divergence as a failing assertion."""
        expected = self.expected[1]
        actual = self.actual[1]
        self.assertEqual(actual.rule_id, expected["rule_id"])
        self.assertEqual(
            actual.verdict, expected["verdict"],
            msg=(
                f"Comparator verdict ({actual.verdict!r}) disagrees "
                f"with canonical ({expected['verdict']!r}). Likely "
                "cause: ``_prescribes_quality`` doesn't recognize "
                "canonical key ``expected_chord_quality``. Fix in "
                "comparator.py, not this test."
            ),
        )
        self.assertIsInstance(actual.evidence, ChordToneMembershipEvidence)
        self.assertEqual(
            actual.evidence.matched, expected["evidence"]["matched"],
        )
        self.assertEqual(
            actual.evidence.total, expected["evidence"]["total"],
        )

    def test_verdict_avoid_scale_drift_satisfies(self):
        """Canonical uses ``max_scale_drift_semitones`` key and expects
        distinct median/max/drift_frame_count. Surfaces both the key
        name divergence AND the ScaleDriftEvidence shape divergence."""
        expected = self.expected[2]
        actual = self.actual[2]
        self.assertEqual(actual.rule_id, expected["rule_id"])
        self.assertEqual(actual.rule_polarity, "avoid")
        self.assertEqual(
            actual.verdict, expected["verdict"],
            msg=(
                f"Comparator verdict ({actual.verdict!r}) disagrees "
                f"with canonical ({expected['verdict']!r}). Likely "
                "cause: ``_prescribes_scale_constraint`` doesn't "
                "recognize canonical key ``max_scale_drift_semitones``."
            ),
        )
        self.assertIsInstance(actual.evidence, ScaleDriftEvidence)
        self.assertEqual(
            actual.evidence.median_drift_semitones,
            expected["evidence"]["median_drift_semitones"],
            msg=(
                "ScaleDriftEvidence.median_drift_semitones diverged "
                "from canonical. Our evaluator currently reuses "
                "obs.scale_drift_semitones for all three fields; "
                "canonical expects per-frame computation."
            ),
        )
        self.assertEqual(
            actual.evidence.max_drift_semitones,
            expected["evidence"]["max_drift_semitones"],
        )
        self.assertEqual(
            actual.evidence.drift_frame_count,
            expected["evidence"]["drift_frame_count"],
            msg=(
                "drift_frame_count must be counted against the rule's "
                "``max_scale_drift_semitones`` threshold, not "
                "len(played_pitches)."
            ),
        )

    def test_composite_confidence_identity(self):
        """§10.6: verdict_confidence == observation_confidence × evaluability."""
        for actual in self.actual:
            expected_composite = (
                self.observation.observation_confidence
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
