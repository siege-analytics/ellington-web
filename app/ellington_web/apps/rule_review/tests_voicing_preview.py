"""Tests for rule_detail voicing preview + confirm_rule voicing pin (#286)."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import UserProfile
from apps.engine_rules.models import EngineRule, EngineRulesBundle
from apps.rule_review.models import PedagogueConfirmation
from apps.styles.models import Master
from apps.voicings.models import Voicing, VoicingBundle


User = get_user_model()


def _make_pedagogue(username: str) -> User:
    u = User.objects.create_user(
        username=username, password=secrets.token_urlsafe(16),
    )
    UserProfile.objects.create(user=u, is_pedagogue=True)
    return u


def _make_rule_bundle():
    return EngineRulesBundle.objects.create(
        bundle_version="0.2.0",
        schema_version="0.2",
        plugin_commit_sha="a" * 40,
        built_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        total_rules=0,
        manifest={"bundle_version": "0.2.0"},
    )


def _make_rule(bundle, master, *, quality_binding, then_action=None):
    return EngineRule.objects.create(
        bundle=bundle, master=master,
        work_id="test", rule_id="r-detail",
        name="test rule", preference=1,
        quality_binding=quality_binding,
        applicability_reasons=[],
        when_predicate={},
        then_action=then_action or {},
        is_active=True,
    )


def _make_voicing_bundle():
    return VoicingBundle.objects.create(
        plugin_commit_sha="b" * 40,
        source_url="https://example.invalid/voicings.json",
        built_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        total_voicings=0,
        raw_top_level={},
    )


def _make_voicing(vbundle, *, voicing_id, chord_quality, category="shell"):
    return Voicing.objects.create(
        bundle=vbundle,
        voicing_id=voicing_id,
        name=f"{chord_quality} {category}",
        chord_quality=chord_quality,
        root="C",
        category=category,
        strings=6,
        tuning="",
        fret_number=3,
        visible_frets=5,
        dots=[{"string": 1, "fret": 1}],
        mutes=[],
        open_strings=[],
        is_active=True,
    )


class RuleDetailVoicingPreviewTests(TestCase):
    def setUp(self):
        self.ebundle = _make_rule_bundle()
        self.master = Master.objects.create(slug="jp", name="Joe Pass")
        self.vbundle = _make_voicing_bundle()
        self.pedagogue = _make_pedagogue("trevor")

    def test_empty_state_when_no_matching_voicing(self):
        rule = _make_rule(self.ebundle, self.master, quality_binding=["maj7"])
        # No voicings ingested at all
        self.client.force_login(self.pedagogue)
        response = self.client.get(
            reverse("rule_review:rule_detail", args=[rule.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No matching voicing in the ingested corpus")

    def test_single_voicing_renders_svg(self):
        rule = _make_rule(self.ebundle, self.master, quality_binding=["min7"])
        v = _make_voicing(self.vbundle, voicing_id="v1", chord_quality="min7")
        self.client.force_login(self.pedagogue)
        response = self.client.get(
            reverse("rule_review:rule_detail", args=[rule.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<svg")
        self.assertContains(response, v.name)
        # Hidden input pins the sole candidate
        self.assertContains(
            response, f'name="voicing_id" value="{v.pk}"',
        )

    def test_multiple_voicings_render_radio_group(self):
        rule = _make_rule(self.ebundle, self.master, quality_binding=["dom7"])
        v_shell = _make_voicing(
            self.vbundle, voicing_id="v1",
            chord_quality="dom7", category="shell",
        )
        v_drop2 = _make_voicing(
            self.vbundle, voicing_id="v2",
            chord_quality="dom7", category="drop2",
        )
        self.client.force_login(self.pedagogue)
        response = self.client.get(
            reverse("rule_review:rule_detail", args=[rule.pk])
        )
        self.assertContains(response, 'type="radio"')
        self.assertContains(response, f'value="{v_shell.pk}"')
        self.assertContains(response, f'value="{v_drop2.pk}"')

    def test_confirm_persists_voicing_pin(self):
        rule = _make_rule(self.ebundle, self.master, quality_binding=["min7"])
        v = _make_voicing(self.vbundle, voicing_id="v1", chord_quality="min7")
        self.client.force_login(self.pedagogue)
        response = self.client.post(
            reverse("rule_review:confirm_rule", args=[rule.pk]),
            {
                "voicing_confirmed": "1",
                "voicing_id": str(v.pk),
                "voicing_note": "",
                "naming_note": "",
                "lesson_note": "",
                "overall_confidence": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        confirmation = PedagogueConfirmation.objects.get(
            rule=rule, user=self.pedagogue,
        )
        self.assertEqual(confirmation.voicing_id, v.pk)
        self.assertTrue(confirmation.voicing_confirmed)

    def test_confirm_rejects_off_rule_voicing_id(self):
        """Pedagogue can't pin a voicing that isn't a candidate for
        this rule — resolver's candidate set is the whitelist."""
        rule = _make_rule(self.ebundle, self.master, quality_binding=["min7"])
        # This voicing has quality "maj7" — NOT a candidate for a
        # min7-bound rule.
        off_rule = _make_voicing(
            self.vbundle, voicing_id="off", chord_quality="maj7",
        )
        self.client.force_login(self.pedagogue)
        response = self.client.post(
            reverse("rule_review:confirm_rule", args=[rule.pk]),
            {
                "voicing_confirmed": "1",
                "voicing_id": str(off_rule.pk),
            },
        )
        self.assertEqual(response.status_code, 302)
        # Confirmation should NOT have been persisted with the bad pin
        self.assertFalse(
            PedagogueConfirmation.objects.filter(
                rule=rule, user=self.pedagogue,
            ).exists()
        )

    def test_confirm_allows_null_voicing_when_no_candidate(self):
        """Rule with no candidate voicings — confirmation still persists
        with voicing=None."""
        rule = _make_rule(self.ebundle, self.master, quality_binding=["maj7"])
        self.client.force_login(self.pedagogue)
        response = self.client.post(
            reverse("rule_review:confirm_rule", args=[rule.pk]),
            {
                "voicing_confirmed": "1",
                "voicing_id": "",  # no pin
                "voicing_note": "no diagram, confirming at schema level",
            },
        )
        self.assertEqual(response.status_code, 302)
        confirmation = PedagogueConfirmation.objects.get(
            rule=rule, user=self.pedagogue,
        )
        self.assertIsNone(confirmation.voicing_id)
        self.assertTrue(confirmation.voicing_confirmed)
