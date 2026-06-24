"""Tests for the engine-rules firing engine (#177).

Spec §8 worked examples are used VERBATIM as fixtures. If the impl's
output diverges from any §8 expected RuleFireResult, the impl is wrong
(not the spec). This is the runnable-not-prose anchor for the
cross-project contract.

Plus unit coverage for §2.2 family-hierarchical matching, §2.3 aliases,
§1 when predicate semantics (literal / array / "any" / absent), and
the chord_quality augmentation table from §3.
"""

from __future__ import annotations

from unittest import TestCase

from apps.engine_rules.firing import (
    RuleFireResult,
    Slice,
    augment,
    augment_chord_quality,
    family_of,
    fire,
    fire_all,
    normalize_quality_token,
)


# ---------------------------------------------------------------------------
# §3 augmentation table — core canonical token derivations
# ---------------------------------------------------------------------------


class ChordQualityAugmentationTests(TestCase):
    """Spec §3 augmentation table — most-specific token wins."""

    def test_maj7_family(self):
        self.assertEqual(augment_chord_quality("Cmaj7"), "maj7")
        self.assertEqual(augment_chord_quality("Cmaj9"), "maj9")
        self.assertEqual(augment_chord_quality("Cmaj13"), "maj13")
        self.assertEqual(augment_chord_quality("Cmaj7#11"), "maj7#11")
        self.assertEqual(augment_chord_quality("Cmaj7(#11)"), "maj7#11")
        self.assertEqual(augment_chord_quality("C6"), "maj6")
        self.assertEqual(augment_chord_quality("C6/9"), "maj69")

    def test_dominant_family(self):
        self.assertEqual(augment_chord_quality("C7"), "dom7")
        self.assertEqual(augment_chord_quality("G7"), "dom7")
        self.assertEqual(augment_chord_quality("C9"), "dom9")
        self.assertEqual(augment_chord_quality("C13"), "dom13")
        self.assertEqual(augment_chord_quality("C7b5"), "dom7b5")
        self.assertEqual(augment_chord_quality("C7b9"), "dom7b9")
        self.assertEqual(augment_chord_quality("C7(b9)"), "dom7b9")
        self.assertEqual(augment_chord_quality("C7#11"), "dom7#11")
        self.assertEqual(augment_chord_quality("C7sus4"), "dom7sus4")
        self.assertEqual(augment_chord_quality("C7alt"), "alt7")
        self.assertEqual(augment_chord_quality("Calt"), "alt7")

    def test_minor_family(self):
        self.assertEqual(augment_chord_quality("Cm7"), "min7")
        self.assertEqual(augment_chord_quality("Cmin7"), "min7")
        self.assertEqual(augment_chord_quality("Cm9"), "min9")
        self.assertEqual(augment_chord_quality("Cm6"), "min6")
        self.assertEqual(augment_chord_quality("CmMaj7"), "minMaj7")
        self.assertEqual(augment_chord_quality("Cm7b5"), "min7b5")
        self.assertEqual(augment_chord_quality("Cø"), "min7b5")

    def test_dim_aug_sus(self):
        self.assertEqual(augment_chord_quality("Cdim"), "dim")
        self.assertEqual(augment_chord_quality("Cdim7"), "dim7")
        self.assertEqual(augment_chord_quality("Caug"), "aug")
        self.assertEqual(augment_chord_quality("C+"), "aug")
        self.assertEqual(augment_chord_quality("Csus2"), "sus2")
        self.assertEqual(augment_chord_quality("Csus4"), "sus4")
        # Bare "sus" defaults to sus4 per §3
        self.assertEqual(augment_chord_quality("Csus"), "sus4")

    def test_bare_root_is_major(self):
        self.assertEqual(augment_chord_quality("C"), "maj")
        self.assertEqual(augment_chord_quality("F#"), "maj")
        self.assertEqual(augment_chord_quality("Bb"), "maj")


# ---------------------------------------------------------------------------
# §2.2 family-hierarchical matching
# ---------------------------------------------------------------------------


class FamilyHierarchicalMatchingTests(TestCase):
    """Spec §2.2 table — verbatim."""

    def setUp(self):
        # Helper: build a minimal slice with a target chord, augment.
        self.s = lambda chord: augment(Slice(target_chord_canonical=chord))

    def _fires(self, binding, target_chord) -> bool:
        rule = {"rule_id": "test", "preference": 1, "quality_binding": binding, "when": {}}
        return fire(rule, self.s(target_chord)) is not None

    def test_family_maj_matches_maj7(self):
        self.assertTrue(self._fires(["maj"], "Cmaj7"))

    def test_family_maj_matches_maj9(self):
        self.assertTrue(self._fires(["maj"], "Cmaj9"))

    def test_specific_maj7_does_not_match_maj9(self):
        self.assertFalse(self._fires(["maj7"], "Cmaj9"))

    def test_specific_in_array_matches(self):
        self.assertTrue(self._fires(["maj7", "maj9"], "Cmaj9"))

    def test_family_dom7_matches_dom7b9(self):
        # The §2.2 spec note: dom7 is BOTH a specific and a family head.
        # The family layer should catch dom7b9.
        self.assertTrue(self._fires(["dom7"], "C7b9"))

    def test_specific_dom7b9_does_not_match_plain_dom7(self):
        self.assertFalse(self._fires(["dom7b9"], "C7"))

    def test_array_with_family_parent_matches_dom9(self):
        self.assertTrue(self._fires(["dom7", "min7"], "C9"))

    def test_family_sus_matches_sus4(self):
        self.assertTrue(self._fires(["sus"], "Csus4"))

    def test_specific_sus4_does_not_match_sus2(self):
        self.assertFalse(self._fires(["sus4"], "Csus2"))

    def test_wildcard_any_always_matches(self):
        self.assertTrue(self._fires(["any"], "Cmaj7"))
        self.assertTrue(self._fires(["any"], "Csus2"))


# ---------------------------------------------------------------------------
# §2.3 alias table
# ---------------------------------------------------------------------------


class AliasNormalizationTests(TestCase):
    """Authors may write legacy shorthand; engine normalizes at firing."""

    def test_seventh_to_dom7(self):
        self.assertEqual(normalize_quality_token("seventh"), "dom7")

    def test_major7_to_maj7(self):
        self.assertEqual(normalize_quality_token("major7"), "maj7")

    def test_minor_to_min_family(self):
        self.assertEqual(normalize_quality_token("minor"), "min")

    def test_unicode_alias(self):
        self.assertEqual(normalize_quality_token("Δ"), "maj7")
        self.assertEqual(normalize_quality_token("ø"), "min7b5")

    def test_canonical_passthrough(self):
        # Canonical tokens should pass unchanged
        self.assertEqual(normalize_quality_token("dom7b9"), "dom7b9")
        self.assertEqual(normalize_quality_token("minMaj7"), "minMaj7")


# ---------------------------------------------------------------------------
# §1 when predicate semantics
# ---------------------------------------------------------------------------


class WhenPredicateTests(TestCase):

    def setUp(self):
        # Slice with rich facets so we can exercise all dimensions.
        self.slice = augment(Slice(
            target_chord_canonical="G7",
            key="C",
            section_label="A",
            arrangement_style="solo_guitar",
            progression_position="V",
        ))

    def _fire(self, when, quality_binding=None):
        rule = {
            "rule_id": "test", "preference": 1,
            "quality_binding": quality_binding or ["any"],
            "when": when,
        }
        return fire(rule, self.slice)

    def test_literal_match(self):
        self.assertIsNotNone(self._fire({"key": "C"}))

    def test_literal_mismatch(self):
        self.assertIsNone(self._fire({"key": "D"}))

    def test_array_or_match(self):
        self.assertIsNotNone(self._fire({"key": ["D", "C", "F"]}))

    def test_array_or_mismatch(self):
        self.assertIsNone(self._fire({"key": ["D", "E"]}))

    def test_any_wildcard_matches(self):
        self.assertIsNotNone(self._fire({"key": "any"}))

    def test_any_matches_null(self):
        # Slice has no melody_note (null); when: {"melody_note": "any"} should fire
        self.assertIsNotNone(self._fire({"melody_note": "any"}))

    def test_constraint_against_null_slice_dim_does_not_fire(self):
        # Slice has melody_note=None; rule requires a specific note → no fire
        self.assertIsNone(self._fire({"melody_note": "C"}))

    def test_dotted_key_arrangement_style(self):
        self.assertIsNotNone(self._fire({"arrangement.style": "solo_guitar"}))

    def test_dotted_key_progression_position(self):
        self.assertIsNotNone(self._fire({"progression.position": "V"}))

    def test_conjunctive_and(self):
        # Both must match
        self.assertIsNotNone(self._fire({
            "key": "C", "progression.position": "V",
        }))
        # One mismatch → no fire
        self.assertIsNone(self._fire({
            "key": "C", "progression.position": "I",
        }))

    def test_absent_when_key_is_no_constraint(self):
        # Empty when: should fire purely on quality_binding
        self.assertIsNotNone(self._fire({}))

    def test_extra_dotted_key_uses_slice_extra(self):
        self.slice.extra["practice.schedule"] = "daily"
        self.assertIsNotNone(self._fire({"practice.schedule": "daily"}))
        self.assertIsNotNone(self._fire({"practice.schedule": "any"}))
        self.assertIsNone(self._fire({"practice.schedule": "weekly"}))


# ---------------------------------------------------------------------------
# §8 — worked examples (verbatim from spec)
# ---------------------------------------------------------------------------


class WorkedExample1JoePassPositiveFireTests(TestCase):
    """§8 Example 1 — positive fire, Joe Pass.

    Rule (after #555 migration):
        when: { "chord_quality": "dom7",
                "progression.position": "cycle_node" }
        then: { "voicing.shape": "seventh_catalog_form" }
        preference: 1
        quality_binding: ["dom7", "maj7", "min7"]

    Slice: target_chord = "G7", progression.position = "cycle_node".
    Expected: fires; matched_dimensions records the matched values.
    """

    def test_fires_with_expected_result_shape(self):
        rule = {
            "rule_id": "pass-seventh-cycle-origin",
            "when": {
                "chord_quality": "dom7",
                "progression.position": "cycle_node",
            },
            "then": {"voicing.shape": "seventh_catalog_form"},
            "preference": 1,
            "quality_binding": ["dom7", "maj7", "min7"],
        }
        slice_ = augment(Slice(
            target_chord_canonical="G7",
            progression_position="cycle_node",
        ))

        result = fire(rule, slice_)

        self.assertIsNotNone(result)
        self.assertEqual(result.rule_id, "pass-seventh-cycle-origin")
        self.assertEqual(result.preference, 1)
        self.assertEqual(result.polarity, "positive")
        self.assertEqual(
            result.then_action,
            {"voicing.shape": "seventh_catalog_form"},
        )
        self.assertEqual(
            result.matched_dimensions,
            {"chord_quality": "dom7", "progression.position": "cycle_node"},
        )
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.applicability_reasons, [])


class WorkedExample2LaukensAvoidFireTests(TestCase):
    """§8 Example 2 — avoid fire, Laukens (after #555).

    quality_binding: ["any"]; when keyed off arrangement.style alone.
    """

    def test_fires_with_expected_polarity_and_reasons(self):
        rule = {
            "rule_id": "laukens-back-cycling-not-band-context",
            "when": {"arrangement.style": "band_with_others_on_chart"},
            "then": {"chord_symbol.substitute": "none_use_original_chart"},
            "preference": -1,
            "quality_binding": ["any"],
            "applicability_reasons": ["arrangement_context"],
        }
        slice_ = augment(Slice(
            target_chord_canonical="Dm7",
            arrangement_style="band_with_others_on_chart",
        ))

        result = fire(rule, slice_)

        self.assertIsNotNone(result)
        self.assertEqual(result.rule_id, "laukens-back-cycling-not-band-context")
        self.assertEqual(result.preference, -1)
        self.assertEqual(result.polarity, "avoid")
        self.assertEqual(
            result.then_action,
            {"chord_symbol.substitute": "none_use_original_chart"},
        )
        self.assertEqual(
            result.matched_dimensions,
            {"arrangement.style": "band_with_others_on_chart"},
        )
        self.assertEqual(result.applicability_reasons, ["arrangement_context"])

    def test_does_not_fire_when_arrangement_style_differs(self):
        rule = {
            "rule_id": "laukens-back-cycling-not-band-context",
            "when": {"arrangement.style": "band_with_others_on_chart"},
            "preference": -1,
            "quality_binding": ["any"],
        }
        slice_ = augment(Slice(
            target_chord_canonical="Dm7",
            arrangement_style="solo_guitar",
        ))
        self.assertIsNone(fire(rule, slice_))


class WorkedExample3RobertsStrongAvoidFireTests(TestCase):
    """§8 Example 3 — strong_avoid (-2) fire, Roberts.

    Practice-context rule keyed off a dotted-key facet outside the
    spec's canonical dimensions (practice.schedule). The engine
    must reach it via slice.extra.
    """

    def test_fires_with_strong_avoid_polarity(self):
        rule = {
            "rule_id": "roberts-20w-no-skip-days",
            "when": {"practice.schedule": "any"},
            "then": {"session.skip": False},
            "preference": -2,
            "quality_binding": ["any"],
        }
        slice_ = augment(Slice(
            target_chord_canonical="C",
            extra={"practice.schedule": "weekly"},
        ))

        result = fire(rule, slice_)

        self.assertIsNotNone(result)
        self.assertEqual(result.rule_id, "roberts-20w-no-skip-days")
        self.assertEqual(result.preference, -2)
        self.assertEqual(result.polarity, "avoid")  # negative regardless of magnitude


# ---------------------------------------------------------------------------
# fire_all batch convenience
# ---------------------------------------------------------------------------


class FireAllTests(TestCase):

    def test_fire_all_filters_to_matches(self):
        slice_ = Slice(target_chord_canonical="C7")
        rules = [
            {  # fires — dom7 family
                "rule_id": "dom-fires",
                "quality_binding": ["dom7"],
                "when": {},
                "preference": 1,
            },
            {  # does not fire — minor family
                "rule_id": "min-no-fire",
                "quality_binding": ["min"],
                "when": {},
                "preference": 1,
            },
            {  # fires — wildcard
                "rule_id": "any-fires",
                "quality_binding": ["any"],
                "when": {},
                "preference": 0,
            },
        ]
        results = fire_all(rules, slice_)
        ids = [r.rule_id for r in results]
        self.assertEqual(set(ids), {"dom-fires", "any-fires"})


# ---------------------------------------------------------------------------
# family_of helper
# ---------------------------------------------------------------------------


class FamilyOfTests(TestCase):

    def test_family_of_specifics(self):
        self.assertEqual(family_of("maj7"), "maj")
        self.assertEqual(family_of("min9"), "min")
        self.assertEqual(family_of("dom7b9"), "dom7")
        self.assertEqual(family_of("alt7"), "dom7")
        self.assertEqual(family_of("dim7"), "dim")
        self.assertEqual(family_of("sus4"), "sus")

    def test_family_of_family_parent_is_self(self):
        self.assertEqual(family_of("maj"), "maj")
        self.assertEqual(family_of("dom7"), "dom7")

    def test_family_of_wildcard(self):
        self.assertEqual(family_of("any"), "any")
