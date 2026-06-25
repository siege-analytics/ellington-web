"""v0.1 per-slice comparator (#248).

Given a list of ``RuleFireResult`` from the firing engine + a
``SliceObservation`` from the audio pipeline, produce a list of
``RuleVerdict`` per the locked §10 contract (apps.audio.contract).

v0.1 evaluable subset (§10.7):
- ``then`` prescribes a chord quality / family → chord-tone membership
- ``then`` prescribes scale-tone constraints → scale drift threshold
- Otherwise → ``DeferredEvidence`` + ``neutral`` verdict

Pure-Python: no DB, no Celery, no audio dependency. Built against the
typed dataclasses so it's fully testable in isolation.

Per child #248 of #232.

Per-evidence verdict construction (cross-project: candidate text for
firing-spec §10.4.1 per plugin agent ack of comparator-semantics
bug surfaced by parity oracle PR #256 + fixed in PR #258 / #257)
============================================================

**The §10.4 polarity × played-content table is the consumer-facing
output, not a uniform algorithm.** Each evidence variant defines its
own implicit "did the prescribed thing" predicate. Verdict is
constructed from that predicate combined with polarity, not from a
generic predicate that gets flipped by polarity.

Per-evidence predicate table (canonical):

| Evidence variant         | "Did the prescribed thing" predicate           | Polarity-relative? |
|--------------------------|------------------------------------------------|--------------------|
| ChordToneMembership      | matched_chord_tones / total ≥ 0.75 AND no off  | YES                |
|                          | positive + predicate=T → satisfies             |                    |
|                          | positive + predicate=F → violates              |                    |
|                          | avoid    + predicate=T → violates              |                    |
|                          | avoid    + predicate=F → satisfies             |                    |
|--------------------------|------------------------------------------------|--------------------|
| ScaleDrift               | scale_drift_semitones ≤ threshold (low drift)  | NO                 |
|                          | Both 'positive: stay on scale' and 'avoid:     |                    |
|                          | don't drift' want low drift. Verdict label     |                    |
|                          | is the SAME regardless of polarity:            |                    |
|                          | low drift → satisfies                          |                    |
|                          | high drift → violates                          |                    |
|--------------------------|------------------------------------------------|--------------------|
| Deferred                 | (no predicate — verdict is always neutral)     | N/A                |
| VoicingMatch (v2)        | TBD per voicing_match spec                     | TBD                |
| RhythmAttack (v2)        | TBD per rhythm_attack spec                     | TBD                |

**Why scale_drift is polarity-invariant:** the "thing" the rule
names (drift) is exactly what BOTH 'positive: stay on scale' AND
'avoid: don't drift' rules want absent. Low drift satisfies the
positive rule (stayed on scale) AND satisfies the avoid rule
(didn't drift). The polarity is informational ("which kind of rule")
but doesn't flip the satisfies/violates assignment.

**Why chord_tone_membership is polarity-relative:** the "thing"
(playing the chord tones) is what 'positive' rules want and what
'avoid' rules want absent. Polarity literally flips the meaning
of "did the player do the prescribed thing."

The general principle: when authoring a new evidence variant, define
the variant's predicate semantics first, THEN decide whether polarity
flips. Don't assume uniform flip.
"""

from __future__ import annotations

from typing import Iterable

from apps.audio.contract import (
    ChordToneMembershipEvidence,
    DeferredEvidence,
    EvidenceUnion,
    RuleVerdict,
    ScaleDriftEvidence,
    SliceObservation,
)
from apps.engine_rules.firing import RuleFireResult


# Below this composite confidence, even an evaluable rule renders as
# ``indeterminate`` instead of satisfies/violates — the underlying
# observation is too unreliable to call.
_INDETERMINATE_THRESHOLD = 0.3

# Scale-drift threshold (semitones). At or below = on-scale (satisfies
# a "stay on this scale" positive-polarity rule). Above = off-scale
# (violates).
_SCALE_DRIFT_THRESHOLD_SEMITONES = 0.5


def compare_slice(
    rule_fires: Iterable[RuleFireResult],
    observation: SliceObservation,
) -> list[RuleVerdict]:
    """Produce one RuleVerdict per fired rule.

    The evaluator is intentionally explicit about what it can / cannot
    grade. Rule shapes outside the v0.1 evaluable subset get
    ``DeferredEvidence`` with a ``neutral`` verdict — better than a
    false-positive verdict.
    """
    verdicts: list[RuleVerdict] = []
    for rule in rule_fires:
        verdicts.append(_evaluate_one(rule, observation))
    return verdicts


def _evaluate_one(
    rule: RuleFireResult, obs: SliceObservation,
) -> RuleVerdict:
    """Pick an evaluator based on the ``then_action`` shape.

    Each evaluator returns the verdict DIRECTLY given (polarity,
    observation) — uniform polarity-flip was wrong for scale_drift
    per parity oracle PR #256 + ticket #257.
    """
    then = rule.then_action or {}

    # ----- Quality-prescribing rules → chord-tone membership ---------
    if _prescribes_quality(then):
        evidence, verdict_label = _evaluate_chord_tone_membership(
            obs, rule.polarity,
        )
        return _build_verdict(
            rule=rule,
            evidence=evidence,
            verdict_label=verdict_label,
            obs=obs,
            evaluability=1.0,
        )

    # ----- Scale-tone-prescribing rules → scale drift ----------------
    if _prescribes_scale_constraint(then):
        evidence, verdict_label = _evaluate_scale_drift(
            obs, rule.polarity,
        )
        return _build_verdict(
            rule=rule,
            evidence=evidence,
            verdict_label=verdict_label,
            obs=obs,
            evaluability=1.0,
        )

    # ----- Voicing / rhythm / anything else → deferred ---------------
    reason = _deferral_reason(then)
    deferred = DeferredEvidence(
        reason=reason,
        deferred_until_version="v0.2",
    )
    return RuleVerdict(
        slice_id=obs.slice_id,
        rule_id=rule.rule_id,
        rule_polarity=rule.polarity,
        verdict="neutral",
        evidence=deferred,
        verdict_confidence=obs.observation_confidence * 0.0,
        rule_evaluability_confidence=0.0,
    )


# ---------------------------------------------------------------------------
# Rule-shape detection
# ---------------------------------------------------------------------------


def _prescribes_quality(then_action: dict) -> bool:
    """True when the ``then`` action names a chord quality / family
    that we can match against ``observation.matched_chord_tones``."""
    return any(
        key in then_action for key in (
            "chord_quality", "quality", "quality_family",
        )
    )


def _prescribes_scale_constraint(then_action: dict) -> bool:
    """True when the ``then`` action names a scale-tone or scale-context
    constraint we can grade via ``scale_drift_semitones``."""
    return any(
        key in then_action for key in (
            "scale_tones", "stay_on_scale", "scale_context_constraint",
        )
    )


def _deferral_reason(then_action: dict) -> str:
    """Pick a human-readable reason for deferral so the rule_review UI
    can show why a rule was unevaluable."""
    if "voicing" in then_action or "voicing_family" in then_action:
        return (
            "requires polyphonic voicing-shape evaluation "
            "(v0.2: voicing match upgrade)"
        )
    if "rhythm" in then_action or "attack" in then_action:
        return (
            "requires rhythmic-attack analysis "
            "(v0.2: rhythm attack upgrade)"
        )
    return (
        "no v0.1 evaluator matches this then-action shape; "
        "verdict deferred"
    )


# ---------------------------------------------------------------------------
# Evidence builders
# ---------------------------------------------------------------------------


def _evaluate_chord_tone_membership(
    obs: SliceObservation, polarity: str,
) -> tuple[ChordToneMembershipEvidence, str]:
    """Chord-tone-membership IS polarity-relative.

    - positive rule wants the player to play the chord tones
    - avoid rule wants the player NOT to play those tones

    So 'matched_ok' triggers satisfies for positive, violates for avoid.
    """
    evidence = ChordToneMembershipEvidence(
        matched=obs.matched_chord_tones,
        total=obs.total_chord_tones,
        missing=tuple(obs.off_scale_tones),
        extra=tuple(obs.off_chord_tones),
    )
    if obs.total_chord_tones == 0:
        matched_ok = obs.matched_chord_tones > 0
    else:
        coverage = obs.matched_chord_tones / obs.total_chord_tones
        matched_ok = (
            coverage >= 0.75 and len(obs.off_chord_tones) == 0
        )

    if polarity == "positive":
        verdict_label = "satisfies" if matched_ok else "violates"
    else:  # "avoid"
        verdict_label = "violates" if matched_ok else "satisfies"
    return evidence, verdict_label


def _evaluate_scale_drift(
    obs: SliceObservation, polarity: str,
) -> tuple[ScaleDriftEvidence, str]:
    """Scale-drift is NOT polarity-relative — surfaced by parity oracle
    PR #256 + ticket #257.

    Both 'positive: stay on scale' and 'avoid: don't drift off scale'
    rules want the SAME outcome: low drift. The verdict logic is
    identical regardless of polarity for this evidence type. Plugin
    #596's canonical fixture exercises this.
    """
    evidence = ScaleDriftEvidence(
        median_drift_semitones=obs.scale_drift_semitones,
        max_drift_semitones=obs.scale_drift_semitones,
        drift_frame_count=len(obs.played_pitches),
    )
    low_drift = obs.scale_drift_semitones <= _SCALE_DRIFT_THRESHOLD_SEMITONES
    verdict_label = "satisfies" if low_drift else "violates"
    return evidence, verdict_label


# ---------------------------------------------------------------------------
# Verdict construction — polarity × satisfied cross-product
# ---------------------------------------------------------------------------


def _build_verdict(
    *,
    rule: RuleFireResult,
    evidence: EvidenceUnion,
    verdict_label: str,
    obs: SliceObservation,
    evaluability: float,
) -> RuleVerdict:
    """Wrap the per-evaluator verdict_label into a RuleVerdict, applying
    the §10.6 confidence threshold for indeterminate.

    Per #257 fix: each evaluator now produces the verdict directly
    (polarity-aware), so this just threads it through with the
    confidence math. No uniform polarity flip — that broke for
    scale_drift per parity oracle PR #256.
    """
    composite = obs.observation_confidence * evaluability

    if composite < _INDETERMINATE_THRESHOLD:
        verdict = "indeterminate"
    else:
        verdict = verdict_label

    return RuleVerdict(
        slice_id=obs.slice_id,
        rule_id=rule.rule_id,
        rule_polarity=rule.polarity,
        verdict=verdict,
        evidence=evidence,
        verdict_confidence=composite,
        rule_evaluability_confidence=evaluability,
    )


__all__ = ["compare_slice"]
