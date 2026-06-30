"""Engine-rules firing engine v0.2 — Python reference implementation.

Implements ``plugin/docs/engine-rules-firing-spec.md`` v0.2 (the
canonical spec; ratified by plugin maintainer 2026-06-17 / #549, #555;
re-confirmed cross-project on plugin#594 / ellington#226 — line 1 of
the spec doc is the load-bearing version statement).

Plugin runtime does not currently consume engine_rules (confirmed in
#586 design). Ellington owns the reference implementation; plugin v2
will mirror this shape.

Public surface:
- ``Slice`` — the harmonic-context input dataclass (§3)
- ``augment(slice)`` — adds the four facets the engine derives once
  per firing (chord_quality, chord_family, scale_context,
  harmonic_context)
- ``fire(rule, slice)`` — match a single rule against a single slice
  and return ``RuleFireResult`` on match, ``None`` otherwise
- ``fire_all(rules, slice)`` — batch convenience
- ``RuleFireResult`` — the structured output (§6)

The rule input is a plain ``dict`` (not the Django EngineRule model)
so the firing layer is testable without a DB. A small adapter at the
boundary builds the dict from an EngineRule row.

Not implemented in v0.1 (deferred per spec non-goals):
- ``then`` action evaluation (passthrough)
- ``falsifier`` machine evaluation (prose only)
- Cross-rule conflict resolution
- Slice production from ChartImport (separate ticket)

Refs: ellington-web #177 (this), #97 (data layer), #60 epic,
plugin/docs/engine-rules-firing-spec.md v0.2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Optional


# ---------------------------------------------------------------------------
# §2 — Canonical chord-quality token set + family hierarchy + alias table
# ---------------------------------------------------------------------------

# Specific qualities grouped by family. The family parent matches any
# specific quality in its family per §2.2.
_FAMILY_TO_SPECIFICS: dict[str, frozenset[str]] = {
    "maj": frozenset({
        "maj", "maj6", "maj69", "maj7", "maj9", "maj13",
        "maj7#11", "maj7b5",
    }),
    "min": frozenset({
        "min", "min6", "min69", "min7", "min9", "min11", "min13",
        "minMaj7", "min7b5",
    }),
    "dom7": frozenset({
        "dom7", "dom9", "dom11", "dom13",
        "dom7b5", "dom7#5", "dom7b9", "dom7#9", "dom7#11",
        "dom7sus4",
        "alt7",
    }),
    "dim": frozenset({"dim", "dim7"}),
    "aug": frozenset({"aug", "aug7"}),
    "sus": frozenset({"sus2", "sus4"}),
}

# Reverse lookup: specific token → family parent.
_SPECIFIC_TO_FAMILY: dict[str, str] = {
    specific: family
    for family, specifics in _FAMILY_TO_SPECIFICS.items()
    for specific in specifics
}

# Author shorthand / legacy spellings → canonical token (§2.3).
_ALIAS_TABLE: dict[str, str] = {
    "seventh": "dom7",
    "7": "dom7",
    "major": "maj",       # family
    "major7": "maj7",     # specific
    "minor": "min",       # family
    "minor7": "min7",     # specific
    "dominant": "dom7",   # family
    "dominant7": "dom7",  # specific
    "dominant_7": "dom7",
    "half-diminished": "min7b5",
    "diminished": "dim7",
    "+": "aug",
    "°": "dim",
    "ø": "min7b5",
    "m": "min",           # family
    "M": "maj",           # family
    "Δ": "maj7",
}


def normalize_quality_token(token: str) -> str:
    """Resolve aliases per §2.3; pass canonical tokens through unchanged."""
    return _ALIAS_TABLE.get(token, token)


# ---------------------------------------------------------------------------
# §3 — Augmentation: target_chord_canonical → chord_quality + chord_family
# ---------------------------------------------------------------------------

# Order matters — match longest / most specific suffix first. Each
# entry is (regex, canonical_quality). Regex anchors at the END of the
# chord symbol so a "C" root and a "Cm" root both reach the suffix
# correctly.
#
# The regex deliberately allows optional parens around alterations so
# "C7(b9)" augments the same as "C7b9".
_QUALITY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Maj7 + extensions (specific before less-specific)
    (re.compile(r"(?i)maj7\(?#11\)?$"), "maj7#11"),
    (re.compile(r"(?i)maj7\(?b5\)?$"), "maj7b5"),
    (re.compile(r"(?i)maj13$"), "maj13"),
    (re.compile(r"(?i)maj(7)?add9$"), "maj9"),
    (re.compile(r"(?i)maj9$"), "maj9"),
    (re.compile(r"(?i)maj7$"), "maj7"),
    # min-maj7 (write before plain min7 so "mMaj7" doesn't fall to min7)
    (re.compile(r"(?i)m\(?maj7\)?$"), "minMaj7"),
    (re.compile(r"(?i)minMaj7$"), "minMaj7"),
    # min7b5 / half-dim (write before plain min7)
    (re.compile(r"(?i)m7b5$"), "min7b5"),
    (re.compile(r"(?i)min7b5$"), "min7b5"),
    (re.compile(r"^([A-G][#b]?)(∅|ø)$"), "min7b5"),  # Cø, C∅
    # Dim7 / dim
    (re.compile(r"(?i)dim7$"), "dim7"),
    (re.compile(r"(?i)dim$"), "dim"),
    (re.compile(r"^([A-G][#b]?)°7$"), "dim7"),
    (re.compile(r"^([A-G][#b]?)°$"), "dim"),
    # Aug
    (re.compile(r"(?i)aug7$"), "aug7"),
    (re.compile(r"(?i)\+7$"), "aug7"),
    (re.compile(r"(?i)aug$"), "aug"),
    (re.compile(r"^([A-G][#b]?)\+$"), "aug"),
    # Alt7 — author-facing shorthand
    (re.compile(r"(?i)7?alt$"), "alt7"),
    (re.compile(r"(?i)7\(alt\)$"), "alt7"),
    # Dominant family — extensions before plain
    (re.compile(r"(?i)7\(?b9\)?$"), "dom7b9"),
    (re.compile(r"(?i)7\(?#9\)?$"), "dom7#9"),
    (re.compile(r"(?i)7\(?b5\)?$"), "dom7b5"),
    (re.compile(r"(?i)7\(?#5\)?$"), "dom7#5"),
    (re.compile(r"(?i)7\+5$"), "dom7#5"),
    (re.compile(r"(?i)7\(?#11\)?$"), "dom7#11"),
    (re.compile(r"(?i)7sus4?\(?11\)?$"), "dom7sus4"),
    (re.compile(r"(?i)7sus4?$"), "dom7sus4"),
    (re.compile(r"(?i)11$"), "dom11"),
    (re.compile(r"(?i)13$"), "dom13"),
    (re.compile(r"(?i)9$"), "dom9"),
    (re.compile(r"(?i)7$"), "dom7"),
    # Minor (post min7b5 / minMaj7)
    (re.compile(r"(?i)m6/9$"), "min69"),
    (re.compile(r"(?i)m69$"), "min69"),
    (re.compile(r"(?i)min13$"), "min13"),
    (re.compile(r"(?i)m13$"), "min13"),
    (re.compile(r"(?i)min11$"), "min11"),
    (re.compile(r"(?i)m11$"), "min11"),
    (re.compile(r"(?i)min9$"), "min9"),
    (re.compile(r"(?i)m9$"), "min9"),
    (re.compile(r"(?i)min7$"), "min7"),
    (re.compile(r"(?i)m7$"), "min7"),
    (re.compile(r"(?i)min6$"), "min6"),
    (re.compile(r"(?i)m6$"), "min6"),
    (re.compile(r"(?i)min$"), "min"),
    (re.compile(r"(?i)m$"), "min"),
    # Major (bare-root + extensions without "maj" prefix)
    (re.compile(r"(?i)6/9$"), "maj69"),
    (re.compile(r"(?i)69$"), "maj69"),
    (re.compile(r"(?i)6$"), "maj6"),
    # Sus (bare-number defaults to sus4 per §3)
    (re.compile(r"(?i)sus2$"), "sus2"),
    (re.compile(r"(?i)sus4$"), "sus4"),
    (re.compile(r"(?i)sus$"), "sus4"),
    # Bare root (e.g. "C", "G", "F#") — major triad → maj family
    (re.compile(r"^[A-G][#b]?$"), "maj"),
]


def augment_chord_quality(target_chord_canonical: str) -> str:
    """Map a chord symbol to the most-specific canonical token (§3).

    Falls back to the family parent ``maj`` for ambiguous bare roots
    (e.g. ``"C"``). Unrecognized symbols return ``"any"`` so a rule
    keyed off ``quality_binding: ["any"]`` still fires.
    """
    target = (target_chord_canonical or "").strip()
    if not target:
        return "any"
    for pattern, quality in _QUALITY_PATTERNS:
        if pattern.search(target):
            return quality
    return "any"


def family_of(quality: str) -> str:
    """Return the family parent for a specific quality, or the token
    itself if it IS a family parent. Wildcards return ``"any"``."""
    if quality == "any":
        return "any"
    if quality in _FAMILY_TO_SPECIFICS:
        return quality
    return _SPECIFIC_TO_FAMILY.get(quality, quality)


# ---------------------------------------------------------------------------
# Slice + RuleFireResult dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Slice:
    """One unit of harmonic context (§3 slice contract).

    Lead-sheet-sourced dimensions are required (target chord at minimum);
    application-context dimensions are optional. Augmented facets are
    populated by ``augment(slice)``.
    """

    # Lead-sheet dimensions
    target_chord_canonical: str
    prev_chord_canonical: Optional[str] = None
    next_chord_canonical: Optional[str] = None
    melody_note: Optional[str] = None
    key: Optional[str] = None
    section_label: Optional[str] = None
    beat_in_measure: Optional[float] = None
    time_signature: Optional[str] = None

    # Application-context dimensions
    arrangement_style: Optional[str] = None
    progression_type: Optional[str] = None
    progression_position: Optional[str] = None

    # Augmented facets — set by augment()
    chord_quality: Optional[str] = None
    chord_family: Optional[str] = None
    scale_context: Optional[str] = None
    harmonic_context: Optional[str] = None

    # Practice / arbitrary dotted-key facets — open dict so authors
    # can target `"practice.schedule"` etc. without schema churn.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleFireResult:
    """Output shape per spec §6.

    Mirrors the spec's Python form verbatim so the type can be used as
    the cross-project canonical reference.
    """

    rule_id: str
    preference: int
    polarity: Literal["positive", "avoid"]
    then_action: dict
    anchor: str
    source_page: Optional[int]
    matched_dimensions: dict
    confidence: float
    applicability_reasons: list[str]


# ---------------------------------------------------------------------------
# Augmentation
# ---------------------------------------------------------------------------


def augment(slice_: Slice) -> Slice:
    """Populate the four augmented facets on a Slice (§3).

    Mutates AND returns the slice for convenience. Deterministic — same
    input always produces same augmentation.
    """
    quality = augment_chord_quality(slice_.target_chord_canonical)
    slice_.chord_quality = quality
    slice_.chord_family = family_of(quality)
    # scale.context: a v0.1 placeholder. Real inference depends on
    # progression.position vs key analysis (§3). For now we emit a
    # simple key-derived label when key is known.
    if slice_.key:
        slice_.scale_context = f"{slice_.key}_major"
    # harmonic.context: heuristic placeholder. Real inference depends
    # on full progression analysis; v0.1 sets it from progression.
    if slice_.progression_position in {"I", "vi", "IIImaj"}:
        slice_.harmonic_context = "tonic"
    elif slice_.progression_position == "V":
        slice_.harmonic_context = "dominant_function"
    elif slice_.progression_position in {"ii", "IV"}:
        slice_.harmonic_context = "subdominant_function"
    return slice_


# ---------------------------------------------------------------------------
# §2 — quality_binding hard prefilter (with family-hierarchical matching)
# ---------------------------------------------------------------------------


def _quality_binding_matches(quality_binding: Iterable[str], slice_quality: str) -> bool:
    """True if the slice's augmented chord_quality matches any token
    in the rule's quality_binding (§2.2 family-hierarchical)."""
    if slice_quality == "any":
        return True
    slice_family = family_of(slice_quality)
    for raw_token in quality_binding:
        token = normalize_quality_token(raw_token)
        if token == "any":
            return True
        if token == slice_quality:
            return True
        # Family parent matches family member
        if token in _FAMILY_TO_SPECIFICS and slice_quality in _FAMILY_TO_SPECIFICS[token]:
            return True
        # Family-name equivalence (token IS slice_family)
        if token == slice_family:
            return True
    return False


# ---------------------------------------------------------------------------
# §1 — when predicate matching (conjunctive AND)
# ---------------------------------------------------------------------------


def _get_dimension(slice_: Slice, dotted_key: str) -> Any:
    """Resolve a dotted-key dimension lookup on the augmented slice.

    Maps the spec's namespaced facets onto the Slice's attribute layout.
    Unknown dotted keys fall through to ``slice_.extra`` so authors can
    target ``practice.schedule`` etc. without schema changes.
    """
    flat_aliases = {
        "target_chord_canonical": slice_.target_chord_canonical,
        "prev_chord_canonical": slice_.prev_chord_canonical,
        "next_chord_canonical": slice_.next_chord_canonical,
        "melody_note": slice_.melody_note,
        "key": slice_.key,
        "section_label": slice_.section_label,
        "beat_in_measure": slice_.beat_in_measure,
        "time_signature": slice_.time_signature,
        "chord_quality": slice_.chord_quality,
        "chord_family": slice_.chord_family,
    }
    if dotted_key in flat_aliases:
        return flat_aliases[dotted_key]
    if dotted_key == "arrangement.style":
        return slice_.arrangement_style
    if dotted_key == "progression.type":
        return slice_.progression_type
    if dotted_key == "progression.position":
        return slice_.progression_position
    if dotted_key == "scale.context":
        return slice_.scale_context
    if dotted_key == "harmonic.context":
        return slice_.harmonic_context
    return slice_.extra.get(dotted_key)


def _value_matches(constraint: Any, slice_value: Any) -> bool:
    """One when-key match per §1 value-shape table."""
    if constraint == "any":
        return True
    if isinstance(constraint, list):
        return any(_value_matches(elem, slice_value) for elem in constraint)
    # Literal scalar — exact match
    return constraint == slice_value


def _when_matches(when: dict, slice_: Slice) -> tuple[bool, dict]:
    """Apply spec §1 conjunctive AND across when's keys.

    Returns ``(matched, matched_dimensions)``. ``matched_dimensions``
    records which keys matched on which slice values — populates the
    RuleFireResult.matched_dimensions field per §6.
    """
    matched_dimensions: dict[str, Any] = {}
    for dotted_key, constraint in when.items():
        slice_value = _get_dimension(slice_, dotted_key)
        # quality_binding overrides chord_quality per §2; the prefilter
        # handles that case, but if a rule still puts chord_quality in
        # when, honor it normally here.
        if not _value_matches(constraint, slice_value):
            return False, {}
        matched_dimensions[dotted_key] = slice_value
    return True, matched_dimensions


# ---------------------------------------------------------------------------
# Public API — fire(), fire_all()
# ---------------------------------------------------------------------------


def fire(rule: dict, slice_: Slice) -> Optional[RuleFireResult]:
    """Match a single rule against a single slice.

    The slice MUST be augmented (call ``augment(slice)`` first; or use
    ``fire_all`` which augments once and reuses across rules).

    Returns a populated ``RuleFireResult`` on match, ``None`` otherwise.
    Idempotent / pure — no side effects on rule or slice.
    """
    if slice_.chord_quality is None:
        augment(slice_)

    # §2: hard prefilter on quality_binding
    quality_binding = rule.get("quality_binding") or []
    if not _quality_binding_matches(quality_binding, slice_.chord_quality):
        return None

    # §1: when predicate matching
    when = rule.get("when") or rule.get("when_predicate") or {}
    matched, matched_dimensions = _when_matches(when, slice_)
    if not matched:
        return None

    preference = int(rule.get("preference", 0))
    polarity = "avoid" if preference < 0 else "positive"

    return RuleFireResult(
        rule_id=rule.get("rule_id", ""),
        preference=preference,
        polarity=polarity,
        then_action=dict(rule.get("then") or rule.get("then_action") or {}),
        anchor=rule.get("anchor", ""),
        source_page=rule.get("source_page"),
        matched_dimensions=matched_dimensions,
        confidence=1.0,  # v0.1 placeholder per §6
        applicability_reasons=list(rule.get("applicability_reasons") or []),
    )


def fire_all(rules: Iterable[dict], slice_: Slice) -> list[RuleFireResult]:
    """Fire every rule against the slice; return list of matches.

    Augments the slice once before the loop so per-rule fires don't
    each re-augment.
    """
    if slice_.chord_quality is None:
        augment(slice_)
    results: list[RuleFireResult] = []
    for rule in rules:
        result = fire(rule, slice_)
        if result is not None:
            results.append(result)
    return results


# ---------------------------------------------------------------------------
# Adapter — Django EngineRule model row → fire()-ready dict
# ---------------------------------------------------------------------------


def rule_from_model(rule_obj) -> dict:
    """Materialize an apps.engine_rules.EngineRule row into a plain dict.

    Keeps the firing layer free of Django ORM imports at module scope;
    callers (views, comparator) use this adapter at the boundary.
    """
    return {
        "rule_id": rule_obj.rule_id,
        "preference": rule_obj.preference,
        "quality_binding": list(rule_obj.quality_binding or []),
        "applicability_reasons": list(rule_obj.applicability_reasons or []),
        "when": dict(rule_obj.when_predicate or {}),
        "then": dict(rule_obj.then_action or {}),
        "anchor": rule_obj.anchor or "",
        "source_page": rule_obj.source_page,
    }


__all__ = [
    "Slice",
    "RuleFireResult",
    "augment",
    "augment_chord_quality",
    "family_of",
    "normalize_quality_token",
    "fire",
    "fire_all",
    "rule_from_model",
]
