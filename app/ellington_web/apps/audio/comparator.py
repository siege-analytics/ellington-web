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
    """Pick an evaluator based on the ``then_action`` shape."""
    then = rule.then_action or {}

    # ----- Quality-prescribing rules → chord-tone membership ---------
    if _prescribes_quality(then):
        evidence, satisfied = _evaluate_chord_tone_membership(obs)
        return _build_verdict(
            rule=rule,
            evidence=evidence,
            satisfied=satisfied,
            obs=obs,
            evaluability=1.0,
        )

    # ----- Scale-tone-prescribing rules → scale drift ----------------
    if _prescribes_scale_constraint(then):
        evidence, satisfied = _evaluate_scale_drift(obs)
        return _build_verdict(
            rule=rule,
            evidence=evidence,
            satisfied=satisfied,
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
    obs: SliceObservation,
) -> tuple[ChordToneMembershipEvidence, bool]:
    """Build a ChordToneMembershipEvidence and return whether the
    canonical match condition holds."""
    evidence = ChordToneMembershipEvidence(
        matched=obs.matched_chord_tones,
        total=obs.total_chord_tones,
        missing=tuple(obs.off_scale_tones),
        extra=tuple(obs.off_chord_tones),
    )
    # "Satisfied" here means the player hit ≥ majority of chord tones
    # AND didn't add any non-chord tones. Threshold tunable; defaults
    # conservative so v0.1 doesn't over-claim satisfies.
    if obs.total_chord_tones == 0:
        satisfied = obs.matched_chord_tones > 0
    else:
        coverage = obs.matched_chord_tones / obs.total_chord_tones
        satisfied = coverage >= 0.75 and len(obs.off_chord_tones) == 0
    return evidence, satisfied


def _evaluate_scale_drift(
    obs: SliceObservation,
) -> tuple[ScaleDriftEvidence, bool]:
    evidence = ScaleDriftEvidence(
        median_drift_semitones=obs.scale_drift_semitones,
        max_drift_semitones=obs.scale_drift_semitones,
        drift_frame_count=len(obs.played_pitches),
    )
    satisfied = obs.scale_drift_semitones <= _SCALE_DRIFT_THRESHOLD_SEMITONES
    return evidence, satisfied


# ---------------------------------------------------------------------------
# Verdict construction — polarity × satisfied cross-product
# ---------------------------------------------------------------------------


def _build_verdict(
    *,
    rule: RuleFireResult,
    evidence: EvidenceUnion,
    satisfied: bool,
    obs: SliceObservation,
    evaluability: float,
) -> RuleVerdict:
    """Apply §10.4 polarity × satisfied → verdict + confidence."""
    composite = obs.observation_confidence * evaluability

    if composite < _INDETERMINATE_THRESHOLD:
        verdict = "indeterminate"
    else:
        # §10.4 cross-product:
        # positive × satisfied → satisfies
        # positive × not satisfied → violates
        # avoid × not did-the-thing (satisfied = "didn't do avoided") → satisfies
        # avoid × did-the-thing (satisfied = False here means they did) → violates
        if rule.polarity == "positive":
            verdict = "satisfies" if satisfied else "violates"
        else:  # "avoid"
            # In the avoid-polarity case, `satisfied=True` from
            # _evaluate_chord_tone_membership means the player DID hit
            # the chord tones — which for avoid-polarity is bad.
            verdict = "violates" if satisfied else "satisfies"

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
