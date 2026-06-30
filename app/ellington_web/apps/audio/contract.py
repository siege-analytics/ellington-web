"""Conformance Verdict Contract — Python mirror of firing-spec §10 (#246).

Canonical source of truth: ``plugin/docs/engine-rules-firing-spec.md``
§10 (Conformance Verdict Contract), ratified jointly with the plugin
agent in plugin#595 and ellington#243. Spec at v0.2.1 (additive
doc-only bump).

This module contains the dataclasses ONLY — no business logic.
Comparator implementation lives in a separate downstream module per
the cross-project tested-but-deferred reserved-slot pattern: ship the
shape now, let consumers wire up against it on their own clock.

If this module's field names or types diverge from spec §10, that's
the drift signal — either side should reconcile. A doc-grep test
(see tests_contract.py) catches the most likely drift mode (renaming
a field without updating both).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union


# ---------------------------------------------------------------------------
# §10.2 — SliceObservation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlayedPitch:
    """One sustained pitch in a played slice (§10.2)."""

    pitch_name: str
    """Scientific pitch notation — e.g. ``"C4"``, ``"Bb3"``, ``"F#5"``."""

    duration_s: float
    """How long the pitch sounded within the slice window."""

    confidence: float
    """0..1 — pitch extractor's confidence on this frame."""


@dataclass(frozen=True)
class SliceObservation:
    """Deterministic audio→played-content facts (§10.2).

    Doesn't know rules exist. Carries everything the comparator needs
    to evaluate any RuleVerdict against this slice.
    """

    slice_id: str
    played_pitches: tuple[PlayedPitch, ...] = field(default_factory=tuple)
    played_intervals_relative_to_root: tuple[int, ...] = field(default_factory=tuple)
    inferred_chord_quality: str | None = None
    matched_chord_tones: int = 0
    total_chord_tones: int = 0
    off_chord_tones: tuple[str, ...] = field(default_factory=tuple)
    off_scale_tones: tuple[str, ...] = field(default_factory=tuple)
    scale_drift_semitones: float = 0.0
    alignment_confidence: float = 0.0
    pitch_extraction_confidence: float = 0.0
    observation_confidence: float = 0.0


# ---------------------------------------------------------------------------
# §10.4 — Verdict + Polarity enums
# ---------------------------------------------------------------------------


VerdictLiteral = Literal["satisfies", "violates", "neutral", "indeterminate"]
PolarityLiteral = Literal["positive", "avoid"]


# ---------------------------------------------------------------------------
# §10.5 — Evidence discriminated union
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChordToneMembershipEvidence:
    """v0.1 — count of played pitches matching the chart-notated chord tones."""

    type: Literal["chord_tone_membership"] = "chord_tone_membership"
    matched: int = 0
    total: int = 0
    missing: tuple[str, ...] = field(default_factory=tuple)
    extra: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ScaleDriftEvidence:
    """v0.1 — drift of played pitches from the nearest scale tone."""

    type: Literal["scale_drift"] = "scale_drift"
    median_drift_semitones: float = 0.0
    max_drift_semitones: float = 0.0
    drift_frame_count: int = 0


@dataclass(frozen=True)
class DeferredEvidence:
    """v0.1 — rule fires but its ``then`` is non-evaluable at the
    current pipeline version. The rule_review UI shows a 'verdict
    deferred' affordance with the reason."""

    type: Literal["deferred"] = "deferred"
    reason: str = ""
    deferred_until_version: str = "v0.2"


# v2 placeholders — reserved by §10.5 so consumers know the union will
# grow but can't fail-closed against unknown types in v0.1.
@dataclass(frozen=True)
class VoicingMatchEvidence:
    """v2 reserved — voicing-shape match (chord-melody upgrade)."""

    type: Literal["voicing_match"] = "voicing_match"
    matched_shape_id: str | None = None
    expected_shape_id: str | None = None


@dataclass(frozen=True)
class RhythmAttackEvidence:
    """v2 reserved — rhythmic-attack density / placement match."""

    type: Literal["rhythm_attack"] = "rhythm_attack"
    expected_attack_count: int = 0
    observed_attack_count: int = 0


EvidenceUnion = Union[
    ChordToneMembershipEvidence,
    ScaleDriftEvidence,
    DeferredEvidence,
    VoicingMatchEvidence,
    RhythmAttackEvidence,
]


# ---------------------------------------------------------------------------
# §10.3 — RuleVerdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleVerdict:
    """Per-rule conformance against a SliceObservation (§10.3).

    Verdict semantics per §10.4 polarity × played-content cross-product.
    The two confidence values are per §10.6 — observation_confidence
    drives audio quality, rule_evaluability_confidence drives rule
    complexity; composite verdict_confidence is what consumers
    typically display.
    """

    slice_id: str
    rule_id: str
    rule_polarity: PolarityLiteral
    verdict: VerdictLiteral
    evidence: EvidenceUnion
    verdict_confidence: float = 0.0
    rule_evaluability_confidence: float = 0.0


__all__ = [
    "ChordToneMembershipEvidence",
    "DeferredEvidence",
    "EvidenceUnion",
    "PlayedPitch",
    "PolarityLiteral",
    "RhythmAttackEvidence",
    "RuleVerdict",
    "ScaleDriftEvidence",
    "SliceObservation",
    "VerdictLiteral",
    "VoicingMatchEvidence",
]
