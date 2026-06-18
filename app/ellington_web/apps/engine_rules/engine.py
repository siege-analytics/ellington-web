"""Engine-rules firing engine (PR 2 of #97).

Pure-Python matching: given a slice (master + quality + facets dict)
and the active rule corpus for that master, return the set of rules
that fire and why.

Per firing-spec v0.2 §3-§5:

- ``quality_binding`` is a hard prefilter. Empty array = applies to any
  quality. Non-empty = slice's canonical quality token must be in the
  array; otherwise the rule is skipped before predicate matching.
- ``when_predicate`` is a dict of dotted-key → expected. Expected values:
  - literal (str/int/bool/null) — slice.facets[<dotted-key>] must equal
  - array of literals — slice.facets[<dotted-key>] must be in the array
  - ``"any"`` — wildcards; key need not exist in facets
- All when_predicate keys must match for the rule to fire (AND).
- A rule that fires emits a ``Fire`` carrying the rule pk + the literal
  match witnesses, so the review UI (#98) can show "fired because of X".

The slice extraction layer (ChartImport → Slice list) is a separate
concern that lives in apps.charts and #98. This module deals only in
already-built ``Slice`` values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from apps.engine_rules.models import EngineRule


# Sentinel used by spec's "any" value — a key whose expected value is
# this matches regardless of the slice's value (or absence).
_ANY = "any"


@dataclass(frozen=True)
class Slice:
    """A facet bundle extracted from a lead-sheet chord event.

    ``master_id`` selects the rule corpus (one Master's rules at a
    time). ``quality`` is the canonical chord-quality token (matches
    EngineRule.quality_binding entries post plugin #555). ``facets`` is
    the nested dict the rule's ``when_predicate`` is evaluated against.

    Slices are hashable so callers can dedupe / cache.
    """

    master_id: str
    quality: str
    facets: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        # facets is unhashable in general; rely on identity for the
        # common case (slices generated fresh per chord event).
        return id(self)


@dataclass(frozen=True)
class Fire:
    """One rule firing against one slice.

    ``rule_pk`` references the EngineRule that fired. ``witnesses`` is
    the dict of when_predicate keys → matched slice values, used by
    the review UI to render "fired because X = Y".
    """

    rule_pk: int
    rule_id: str
    witnesses: dict[str, Any]


def _get_dotted(facets: dict[str, Any], dotted_key: str) -> tuple[bool, Any]:
    """Walk ``facets`` by a dotted key (e.g. ``"harmonic.chord.tension"``).

    Returns ``(found, value)`` — ``found`` is False if any segment is
    missing or any intermediate isn't a dict. Callers use the
    ``found`` flag to distinguish "key absent" from "key present but
    value is None".
    """
    cursor: Any = facets
    for segment in dotted_key.split("."):
        if not isinstance(cursor, dict) or segment not in cursor:
            return False, None
        cursor = cursor[segment]
    return True, cursor


def _matches(expected: Any, slice_value: Any, key_found: bool) -> bool:
    """Match one when_predicate entry against the slice value.

    Spec semantics:
    - expected == ``"any"`` → match (regardless of key_found)
    - expected is a list → slice value must be a member; key must be found
    - expected literal → slice value must equal it; key must be found
    """
    if expected == _ANY:
        return True
    if not key_found:
        return False
    if isinstance(expected, list):
        return slice_value in expected
    return slice_value == expected


def _rule_fires(rule: EngineRule, slice_: Slice) -> tuple[bool, dict[str, Any]]:
    """Evaluate one rule against one slice. Returns (fired, witnesses)."""

    # quality_binding hard prefilter
    if rule.quality_binding and slice_.quality not in rule.quality_binding:
        return False, {}

    witnesses: dict[str, Any] = {}
    predicate = rule.when_predicate or {}
    for dotted_key, expected in predicate.items():
        found, value = _get_dotted(slice_.facets, dotted_key)
        if not _matches(expected, value, found):
            return False, {}
        if expected != _ANY:
            witnesses[dotted_key] = value
    return True, witnesses


def fire_for_slice(
    slice_: Slice,
    rules: Iterable[EngineRule] | None = None,
) -> list[Fire]:
    """Run the firing engine against one slice.

    If ``rules`` is None, queries ``EngineRule.objects.filter(
    master__slug=slice_.master_id, is_active=True)``. Callers that
    want to evaluate against a pre-cached or test-synthetic rule set
    can pass it explicitly — this is what conformance tests do.

    Returns Fires in deterministic order (rule pk ascending) so
    diffing against expected-fires.json is stable.
    """
    if rules is None:
        rules = EngineRule.objects.filter(
            master__slug=slice_.master_id, is_active=True,
        ).order_by("pk")

    fires: list[Fire] = []
    for rule in rules:
        fired, witnesses = _rule_fires(rule, slice_)
        if fired:
            fires.append(Fire(
                rule_pk=rule.pk, rule_id=rule.rule_id, witnesses=witnesses,
            ))
    return fires


__all__ = [
    "Fire",
    "Slice",
    "fire_for_slice",
]
