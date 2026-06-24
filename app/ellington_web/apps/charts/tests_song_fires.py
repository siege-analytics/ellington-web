"""Tests for the per-Song fire-results view (#182).

Verifies that given a Song's chords and an active EngineRule corpus,
the view renders one fire per matching (slice, rule) pair, grouped by
section. The view materializes RuleFireResults into the locked
formatter contract shape (#167) so the same data flows here as in
rule_library (#175).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.charts.models import ChordEvent, Measure, Section, Song
from apps.engine_rules.models import EngineRule, EngineRulesBundle
from apps.styles.models import Master


User = get_user_model()


def _make_bundle() -> EngineRulesBundle:
    return EngineRulesBundle.objects.create(
        bundle_version="0.3.0",
        schema_version="0.2",
        plugin_commit_sha="b" * 40,
        built_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
        total_rules=0,
        manifest={"bundle_version": "0.3.0"},
    )


def _make_rule(bundle, master, **overrides) -> EngineRule:
    defaults = dict(
        bundle=bundle, master=master,
        work_id="test-work", rule_id="r1",
        name="test rule", preference=1,
        quality_binding=["any"],
        applicability_reasons=[],
        when_predicate={}, then_action={}, is_active=True,
    )
    defaults.update(overrides)
    return EngineRule.objects.create(**defaults)


def _make_song_with_chords(slug: str = "test-song") -> Song:
    """ii-V-I in C: Dm7, G7, Cmaj7."""
    song = Song.objects.create(
        slug=slug, title="ii-V-I in C", key="C", time_signature="4/4",
    )
    section = Section.objects.create(song=song, label="A", order_index=0)
    m1 = Measure.objects.create(section=section, number_in_section=1)
    ChordEvent.objects.create(measure=m1, beat=Decimal("1.0"), chord_symbol="Dm7")
    ChordEvent.objects.create(measure=m1, beat=Decimal("3.0"), chord_symbol="G7")
    m2 = Measure.objects.create(section=section, number_in_section=2)
    ChordEvent.objects.create(measure=m2, beat=Decimal("1.0"), chord_symbol="Cmaj7")
    return song


class SongRuleFiresViewTests(TestCase):

    def setUp(self):
        self.bundle = _make_bundle()
        self.master = Master.objects.create(slug="test-master", name="Test Master")
        self.user = User.objects.create_user(
            username="user1", password=secrets.token_urlsafe(16),
        )
        self.song = _make_song_with_chords()
        self.url = reverse("charts:song_rule_fires", args=[self.song.pk])

    def test_login_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_renders_with_no_rules_in_corpus(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ii-V-I in C")
        self.assertContains(response, "No active rules in the corpus")

    def test_quality_binding_rules_fire_per_chord(self):
        # Three rules each targeting one quality family
        _make_rule(self.bundle, self.master,
                   rule_id="dom7-rule", name="Dominant rule",
                   quality_binding=["dom7"], preference=1)
        _make_rule(self.bundle, self.master,
                   rule_id="min7-rule", name="Minor rule",
                   quality_binding=["min7"], preference=0)
        _make_rule(self.bundle, self.master,
                   rule_id="maj7-rule", name="Major rule",
                   quality_binding=["maj7"], preference=2)

        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        # Each rule fires exactly once — total = 3
        self.assertContains(response, "3 rules fire across this chart")

        # Each rule name renders
        self.assertContains(response, "Dominant rule")
        self.assertContains(response, "Minor rule")
        self.assertContains(response, "Major rule")

        # Each chord renders
        self.assertContains(response, "Dm7")
        self.assertContains(response, "G7")
        self.assertContains(response, "Cmaj7")

        # Section header renders with the per-section fire count
        self.assertContains(response, "A")
        self.assertContains(response, "(3 fires)")

    def test_matched_dimensions_rendered(self):
        """Engine agent confirmed matched_dimensions is the pedagogy gold."""
        _make_rule(
            self.bundle, self.master,
            rule_id="contextual-rule",
            name="Tonic dominant rule",
            quality_binding=["dom7"],
            when_predicate={"chord_quality": "dom7"},
            preference=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        # The G7 slice's matched_dimensions should show chord_quality=dom7
        self.assertContains(response, "chord_quality=dom7")

    def test_404_on_missing_song(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("charts:song_rule_fires", args=[99999])
        )
        self.assertEqual(response.status_code, 404)

    def test_empty_song_renders_empty_state(self):
        empty = Song.objects.create(
            slug="empty", title="Empty Song",
            key="C", time_signature="4/4",
        )
        _make_rule(self.bundle, self.master, quality_binding=["any"], preference=1)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("charts:song_rule_fires", args=[empty.pk])
        )
        self.assertContains(response, "No rules fire against this chart")

    def test_preference_pill_renders(self):
        _make_rule(
            self.bundle, self.master,
            rule_id="strong-recommend",
            name="Strong recommend rule",
            quality_binding=["dom7"],
            preference=2,
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        # Pref pill data attribute + class
        self.assertContains(response, 'data-pref="2"')
        self.assertContains(response, "rule-token--strong-recommend")

    def test_rule_detail_link_renders(self):
        """Each rule-token should link to the rule_review detail view."""
        rule = _make_rule(
            self.bundle, self.master,
            rule_id="linked", quality_binding=["dom7"], preference=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        rule_detail_url = reverse("rule_review:rule_detail", args=[rule.pk])
        self.assertContains(response, f'href="{rule_detail_url}"')
