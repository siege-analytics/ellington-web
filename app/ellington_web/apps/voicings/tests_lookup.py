"""Tests for apps.voicings.lookup (#286).

Resolver contract:
- Empty quality_binding → empty queryset
- Matches by chord_quality (case-insensitive)
- voicing_family from then_action prefers matching category
- Ordering: family-match, strings=6 first, fret_number asc
"""

from __future__ import annotations

from datetime import datetime, timezone

from django.test import TestCase

from apps.engine_rules.models import EngineRule, EngineRulesBundle
from apps.styles.models import Master
from apps.voicings.lookup import resolve_voicings_for_rule
from apps.voicings.models import Voicing, VoicingBundle


def _make_engine_bundle() -> EngineRulesBundle:
    return EngineRulesBundle.objects.create(
        bundle_version="0.2.0",
        schema_version="0.2",
        plugin_commit_sha="a" * 40,
        built_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        total_rules=0,
        manifest={"bundle_version": "0.2.0"},
    )


def _make_rule(bundle, master, *, quality_binding=None, then_action=None):
    return EngineRule.objects.create(
        bundle=bundle, master=master,
        work_id="test-work",
        rule_id=f"r-{Voicing.objects.count()}-{EngineRule.objects.count()}",
        name="test rule", preference=1,
        quality_binding=quality_binding or [],
        applicability_reasons=[],
        when_predicate={},
        then_action=then_action or {},
        is_active=True,
    )


def _make_voicing_bundle() -> VoicingBundle:
    return VoicingBundle.objects.create(
        plugin_commit_sha="b" * 40,
        source_url="https://example.invalid/voicings.json",
        built_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        total_voicings=0,
        raw_top_level={},
    )


def _make_voicing(
    vbundle,
    *,
    voicing_id="v1",
    chord_quality="maj7",
    category="shell",
    strings=6,
    fret_number=5,
    is_active=True,
    name=None,
):
    return Voicing.objects.create(
        bundle=vbundle,
        voicing_id=voicing_id,
        name=name or f"{chord_quality}-{category}-{voicing_id}",
        chord_quality=chord_quality,
        root="C",
        category=category,
        strings=strings,
        tuning="",
        fret_number=fret_number,
        visible_frets=5,
        dots=[],
        mutes=[],
        open_strings=[],
        is_active=is_active,
    )


class ResolveVoicingsForRuleTests(TestCase):
    def setUp(self):
        self.ebundle = _make_engine_bundle()
        self.master = Master.objects.create(slug="jp", name="Joe Pass")
        self.vbundle = _make_voicing_bundle()

    def test_empty_quality_binding_returns_none(self):
        rule = _make_rule(self.ebundle, self.master, quality_binding=[])
        _make_voicing(self.vbundle, voicing_id="v0")
        self.assertFalse(resolve_voicings_for_rule(rule).exists())

    def test_matches_by_chord_quality(self):
        rule = _make_rule(
            self.ebundle, self.master, quality_binding=["maj7"],
        )
        matched = _make_voicing(
            self.vbundle, voicing_id="v-maj7", chord_quality="maj7",
        )
        _make_voicing(
            self.vbundle, voicing_id="v-min7", chord_quality="min7",
        )
        results = list(resolve_voicings_for_rule(rule))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].pk, matched.pk)

    def test_quality_match_is_case_insensitive(self):
        rule = _make_rule(
            self.ebundle, self.master, quality_binding=["MAJ7"],
        )
        matched = _make_voicing(
            self.vbundle, voicing_id="v-lower", chord_quality="maj7",
        )
        results = list(resolve_voicings_for_rule(rule))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].pk, matched.pk)

    def test_voicing_family_prefers_matching_category(self):
        rule = _make_rule(
            self.ebundle, self.master,
            quality_binding=["dom7"],
            then_action={"voicing_family": "shell"},
        )
        drop2 = _make_voicing(
            self.vbundle, voicing_id="v-drop2",
            chord_quality="dom7", category="drop2",
        )
        shell = _make_voicing(
            self.vbundle, voicing_id="v-shell",
            chord_quality="dom7", category="shell",
        )
        results = list(resolve_voicings_for_rule(rule))
        self.assertEqual(len(results), 2)
        # Shell (family match) sorts first; drop2 second.
        self.assertEqual(results[0].pk, shell.pk)
        self.assertEqual(results[1].pk, drop2.pk)

    def test_orders_6_string_before_7_string(self):
        rule = _make_rule(
            self.ebundle, self.master, quality_binding=["min7"],
        )
        v7 = _make_voicing(
            self.vbundle, voicing_id="v-7str",
            chord_quality="min7", strings=7, fret_number=3,
        )
        v6 = _make_voicing(
            self.vbundle, voicing_id="v-6str",
            chord_quality="min7", strings=6, fret_number=3,
        )
        results = list(resolve_voicings_for_rule(rule))
        self.assertEqual([r.pk for r in results], [v6.pk, v7.pk])

    def test_inactive_voicings_excluded(self):
        rule = _make_rule(
            self.ebundle, self.master, quality_binding=["maj7"],
        )
        _make_voicing(
            self.vbundle, voicing_id="v-inactive",
            chord_quality="maj7", is_active=False,
        )
        self.assertFalse(resolve_voicings_for_rule(rule).exists())

    def test_multiple_qualities_ORed(self):
        rule = _make_rule(
            self.ebundle, self.master,
            quality_binding=["maj7", "min7"],
        )
        v_maj = _make_voicing(
            self.vbundle, voicing_id="v-maj7", chord_quality="maj7",
        )
        v_min = _make_voicing(
            self.vbundle, voicing_id="v-min7", chord_quality="min7",
        )
        _make_voicing(
            self.vbundle, voicing_id="v-dom7", chord_quality="dom7",
        )
        results = list(resolve_voicings_for_rule(rule))
        self.assertEqual(
            {r.pk for r in results}, {v_maj.pk, v_min.pk},
        )
