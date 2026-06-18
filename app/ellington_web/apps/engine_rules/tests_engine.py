"""Tests for the engine-rules firing engine (apps.engine_rules.engine).

Uses real EngineRule + EngineRulesBundle + Master rows so we exercise
the same DB shape the firing engine sees in production. Coverage:

- quality_binding hard prefilter
- when_predicate literal / array / "any" matching
- dotted-key facet walking + key-absent handling
- AND semantics across multiple predicate keys
- deterministic ordering of fires
- fire_for_slice with explicit rules iterable (the conformance-test path)
"""

from __future__ import annotations

from datetime import datetime, timezone

from django.test import TestCase

from apps.engine_rules.engine import Slice, fire_for_slice
from apps.engine_rules.models import EngineRule, EngineRulesBundle
from apps.styles.models import Master


def _make_bundle(**overrides) -> EngineRulesBundle:
    defaults = dict(
        bundle_version="0.2.0",
        schema_version="0.2",
        plugin_commit_sha="a" * 40,
        built_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        total_rules=0,
        manifest={"bundle_version": "0.2.0"},
    )
    defaults.update(overrides)
    return EngineRulesBundle.objects.create(**defaults)


def _make_rule(bundle, master, **overrides) -> EngineRule:
    defaults = dict(
        bundle=bundle,
        master=master,
        work_id="test-work",
        rule_id="r1",
        name="test rule",
        preference=1,
        quality_binding=[],
        applicability_reasons=[],
        when_predicate={},
        then_action={},
        is_active=True,
    )
    defaults.update(overrides)
    return EngineRule.objects.create(**defaults)


class QualityBindingPrefilterTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.pass_m = Master.objects.create(slug="joe-pass", name="Joe Pass")

    def test_empty_quality_binding_matches_any_quality(self):
        rule = _make_rule(self.bundle, self.pass_m, quality_binding=[])
        slice_ = Slice(master_id="joe-pass", quality="maj7", facets={})
        self.assertEqual(len(fire_for_slice(slice_, [rule])), 1)

    def test_non_empty_quality_binding_filters_out_mismatched_quality(self):
        rule = _make_rule(self.bundle, self.pass_m, quality_binding=["dom7"])
        slice_ = Slice(master_id="joe-pass", quality="maj7", facets={})
        self.assertEqual(fire_for_slice(slice_, [rule]), [])

    def test_non_empty_quality_binding_matches_when_quality_in_list(self):
        rule = _make_rule(
            self.bundle, self.pass_m, quality_binding=["dom7", "dom7b9"],
        )
        slice_ = Slice(master_id="joe-pass", quality="dom7b9", facets={})
        fires = fire_for_slice(slice_, [rule])
        self.assertEqual(len(fires), 1)


class WhenPredicateMatchingTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.pass_m = Master.objects.create(slug="joe-pass", name="Joe Pass")

    def test_literal_value_matches(self):
        rule = _make_rule(
            self.bundle, self.pass_m,
            when_predicate={"position": "ii"},
        )
        slice_ = Slice(master_id="joe-pass", quality="min7", facets={"position": "ii"})
        fires = fire_for_slice(slice_, [rule])
        self.assertEqual(len(fires), 1)
        self.assertEqual(fires[0].witnesses, {"position": "ii"})

    def test_literal_value_mismatches(self):
        rule = _make_rule(
            self.bundle, self.pass_m,
            when_predicate={"position": "ii"},
        )
        slice_ = Slice(master_id="joe-pass", quality="min7", facets={"position": "vi"})
        self.assertEqual(fire_for_slice(slice_, [rule]), [])

    def test_array_value_matches_membership(self):
        rule = _make_rule(
            self.bundle, self.pass_m,
            when_predicate={"position": ["ii", "vi"]},
        )
        slice_ = Slice(master_id="joe-pass", quality="min7", facets={"position": "vi"})
        fires = fire_for_slice(slice_, [rule])
        self.assertEqual(len(fires), 1)
        self.assertEqual(fires[0].witnesses, {"position": "vi"})

    def test_any_value_matches_when_key_present(self):
        rule = _make_rule(
            self.bundle, self.pass_m,
            when_predicate={"position": "any"},
        )
        slice_ = Slice(master_id="joe-pass", quality="min7", facets={"position": "iii"})
        self.assertEqual(len(fire_for_slice(slice_, [rule])), 1)

    def test_any_value_matches_when_key_absent(self):
        # "any" is a wildcard — key doesn't need to exist in facets
        rule = _make_rule(
            self.bundle, self.pass_m,
            when_predicate={"position": "any"},
        )
        slice_ = Slice(master_id="joe-pass", quality="min7", facets={})
        self.assertEqual(len(fire_for_slice(slice_, [rule])), 1)

    def test_key_absent_fails_literal_match(self):
        rule = _make_rule(
            self.bundle, self.pass_m,
            when_predicate={"position": "ii"},
        )
        slice_ = Slice(master_id="joe-pass", quality="min7", facets={})
        self.assertEqual(fire_for_slice(slice_, [rule]), [])

    def test_dotted_key_walks_nested_facets(self):
        rule = _make_rule(
            self.bundle, self.pass_m,
            when_predicate={"harmonic.function": "dominant"},
        )
        slice_ = Slice(
            master_id="joe-pass", quality="dom7",
            facets={"harmonic": {"function": "dominant"}},
        )
        fires = fire_for_slice(slice_, [rule])
        self.assertEqual(len(fires), 1)
        self.assertEqual(fires[0].witnesses, {"harmonic.function": "dominant"})

    def test_dotted_key_returns_absent_for_missing_path(self):
        rule = _make_rule(
            self.bundle, self.pass_m,
            when_predicate={"harmonic.function": "dominant"},
        )
        slice_ = Slice(master_id="joe-pass", quality="dom7", facets={"harmonic": {}})
        self.assertEqual(fire_for_slice(slice_, [rule]), [])

    def test_dotted_key_treats_non_dict_segments_as_absent(self):
        rule = _make_rule(
            self.bundle, self.pass_m,
            when_predicate={"harmonic.function": "dominant"},
        )
        slice_ = Slice(
            master_id="joe-pass", quality="dom7",
            facets={"harmonic": "not-a-dict"},
        )
        self.assertEqual(fire_for_slice(slice_, [rule]), [])

    def test_all_predicate_keys_must_match_AND_semantics(self):
        rule = _make_rule(
            self.bundle, self.pass_m,
            when_predicate={"position": "ii", "harmonic.function": "predominant"},
        )
        slice_ok = Slice(
            master_id="joe-pass", quality="min7",
            facets={"position": "ii", "harmonic": {"function": "predominant"}},
        )
        slice_partial = Slice(
            master_id="joe-pass", quality="min7",
            facets={"position": "ii", "harmonic": {"function": "tonic"}},
        )
        self.assertEqual(len(fire_for_slice(slice_ok, [rule])), 1)
        self.assertEqual(fire_for_slice(slice_partial, [rule]), [])


class DeterministicOrderingTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.pass_m = Master.objects.create(slug="joe-pass", name="Joe Pass")

    def test_explicit_rules_iterable_preserves_caller_order(self):
        # When rules iterable is explicit, engine iterates as given —
        # no DB sort applied. Conformance / synthetic-test callers
        # control ordering.
        rules = [
            _make_rule(self.bundle, self.pass_m, rule_id=f"r{i}")
            for i in range(3)
        ]
        slice_ = Slice(master_id="joe-pass", quality="any", facets={})
        fires = fire_for_slice(slice_, list(reversed(rules)))
        self.assertEqual([f.rule_id for f in fires], ["r2", "r1", "r0"])

    def test_db_path_sorts_by_pk(self):
        # Without explicit rules, the engine queries DB ordered by pk.
        for i in range(3):
            _make_rule(self.bundle, self.pass_m, rule_id=f"r{i}")
        slice_ = Slice(master_id="joe-pass", quality="any", facets={})
        fires = fire_for_slice(slice_)
        self.assertEqual([f.rule_id for f in fires], ["r0", "r1", "r2"])


class InactiveAndOtherMasterFilterTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.pass_m = Master.objects.create(slug="joe-pass", name="Joe Pass")
        self.burrell = Master.objects.create(slug="kenny-burrell", name="Kenny Burrell")

    def test_inactive_rules_skipped_via_db_path(self):
        _make_rule(self.bundle, self.pass_m, rule_id="active", is_active=True)
        _make_rule(self.bundle, self.pass_m, rule_id="dead", is_active=False)
        slice_ = Slice(master_id="joe-pass", quality="any", facets={})
        fires = fire_for_slice(slice_)
        self.assertEqual([f.rule_id for f in fires], ["active"])

    def test_other_master_rules_skipped_via_db_path(self):
        _make_rule(self.bundle, self.pass_m, rule_id="pass_rule")
        _make_rule(self.bundle, self.burrell, rule_id="burrell_rule")
        slice_ = Slice(master_id="joe-pass", quality="any", facets={})
        fires = fire_for_slice(slice_)
        self.assertEqual([f.rule_id for f in fires], ["pass_rule"])
