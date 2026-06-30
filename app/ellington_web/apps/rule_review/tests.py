"""Tests for apps.rule_review (epic #96 / #98 focus-group v1)."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.core.models import UserProfile
from apps.engine_rules.models import EngineRule, EngineRulesBundle
from apps.rule_review.models import (
    PedagogueConfirmation,
    RejectionAxis,
    Response,
    RuleComment,
    Verdict,
)
from apps.styles.models import Master


User = get_user_model()


def _make_bundle() -> EngineRulesBundle:
    return EngineRulesBundle.objects.create(
        bundle_version="0.2.0",
        schema_version="0.2",
        plugin_commit_sha="a" * 40,
        built_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        total_rules=0,
        manifest={"bundle_version": "0.2.0"},
    )


def _make_rule(bundle, master, **overrides) -> EngineRule:
    defaults = dict(
        bundle=bundle, master=master,
        work_id="test-work", rule_id="r1",
        name="test rule", preference=1,
        quality_binding=["dom7"], applicability_reasons=[],
        when_predicate={}, then_action={}, is_active=True,
    )
    defaults.update(overrides)
    return EngineRule.objects.create(**defaults)


def _make_pedagogue(username: str) -> User:
    u = User.objects.create_user(
        username=username, password=secrets.token_urlsafe(16),
    )
    UserProfile.objects.create(user=u, is_pedagogue=True)
    return u


class ResponseModelTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.master = Master.objects.create(slug="joe-pass", name="Joe Pass")
        self.rule = _make_rule(self.bundle, self.master)
        self.trevor = _make_pedagogue("trevor")

    def test_unique_per_rule_user(self):
        Response.objects.create(
            rule=self.rule, user=self.trevor, verdict=Verdict.ACCEPT,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Response.objects.create(
                rule=self.rule, user=self.trevor, verdict=Verdict.REJECT,
            )

    def test_update_or_create_flow(self):
        Response.objects.update_or_create(
            rule=self.rule, user=self.trevor,
            defaults={"verdict": Verdict.ACCEPT},
        )
        Response.objects.update_or_create(
            rule=self.rule, user=self.trevor,
            defaults={
                "verdict": Verdict.REJECT,
                "rejection_axis": RejectionAxis.ANCHOR,
                "comment": "anchor misquoted",
            },
        )
        r = Response.objects.get(rule=self.rule, user=self.trevor)
        self.assertEqual(r.verdict, Verdict.REJECT)
        self.assertEqual(r.rejection_axis, RejectionAxis.ANCHOR)
        self.assertEqual(r.comment, "anchor misquoted")


class RuleListViewTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.master = Master.objects.create(slug="joe-pass", name="Joe Pass")
        self.rule = _make_rule(self.bundle, self.master)
        self.trevor = _make_pedagogue("trevor")

    def test_login_required(self):
        response = self.client.get(reverse("rule_review:rule_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_authenticated_user_sees_list(self):
        self.client.force_login(self.trevor)
        response = self.client.get(reverse("rule_review:rule_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "test rule")

    def test_my_verdict_filter_unjudged(self):
        # Trevor hasn't judged → rule shows under "unjudged"
        self.client.force_login(self.trevor)
        response = self.client.get(
            reverse("rule_review:rule_list") + "?my_verdict=unjudged"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "test rule")

        # Trevor judges accept → rule no longer in unjudged
        Response.objects.create(
            rule=self.rule, user=self.trevor, verdict=Verdict.ACCEPT,
        )
        response = self.client.get(
            reverse("rule_review:rule_list") + "?my_verdict=unjudged"
        )
        self.assertNotContains(response, "test rule")


class RuleDetailViewTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.master = Master.objects.create(slug="joe-pass", name="Joe Pass")
        self.rule = _make_rule(self.bundle, self.master)
        self.trevor = _make_pedagogue("trevor")
        self.stranger = User.objects.create_user(
            username="general1", password=secrets.token_urlsafe(16),
        )
        self.url = reverse("rule_review:rule_detail", args=[self.rule.pk])

    def test_get_shows_form_for_pedagogue(self):
        self.client.force_login(self.trevor)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your verdict")

    def test_get_shows_no_form_for_general_user(self):
        self.client.force_login(self.stranger)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "need the Pedagogue role")

    def test_source_locator_renders_page_and_filename(self):
        """#136: 'Page N of <book>' when both source_page and source_pdf_filename set."""
        self.rule.anchor = "voicing must include the 3rd"
        self.rule.source_page = 42
        self.rule.source_pdf_filename = "joe-pass-chord-solos.pdf"
        self.rule.save()
        self.client.force_login(self.stranger)
        response = self.client.get(self.url)
        self.assertContains(response, "Page 42 of joe-pass-chord-solos.pdf")

    def test_source_locator_page_only_when_filename_missing(self):
        """#136: 'Page N' alone when source_pdf_filename is empty."""
        self.rule.anchor = "voicing must include the 3rd"
        self.rule.source_page = 7
        self.rule.source_pdf_filename = ""
        self.rule.save()
        self.client.force_login(self.stranger)
        response = self.client.get(self.url)
        self.assertContains(response, "Page 7")
        # No "Page N of …" — the " of " infix should not appear next to the page.
        self.assertNotContains(response, "Page 7 of")

    def test_source_locator_omitted_when_both_null(self):
        """#136: no locator line when both source_page and source_pdf_filename absent."""
        self.rule.anchor = "voicing must include the 3rd"
        self.rule.source_page = None
        self.rule.source_pdf_filename = ""
        self.rule.save()
        self.client.force_login(self.stranger)
        response = self.client.get(self.url)
        self.assertNotContains(response, "source-locator")

    def test_post_accept_creates_response(self):
        self.client.force_login(self.trevor)
        response = self.client.post(
            self.url,
            {"verdict": Verdict.ACCEPT, "rejection_axis": "", "comment": ""},
        )
        self.assertEqual(response.status_code, 302)
        r = Response.objects.get(rule=self.rule, user=self.trevor)
        self.assertEqual(r.verdict, Verdict.ACCEPT)
        self.assertEqual(r.rejection_axis, "")

    def test_post_reject_without_axis_rejected(self):
        self.client.force_login(self.trevor)
        response = self.client.post(
            self.url,
            {"verdict": Verdict.REJECT, "rejection_axis": "", "comment": "x"},
        )
        # Redirect with flash error; no response saved
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Response.objects.filter(rule=self.rule, user=self.trevor).exists()
        )

    def test_post_reject_without_comment_rejected(self):
        self.client.force_login(self.trevor)
        response = self.client.post(
            self.url,
            {
                "verdict": Verdict.REJECT,
                "rejection_axis": RejectionAxis.ANCHOR,
                "comment": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Response.objects.filter(rule=self.rule, user=self.trevor).exists()
        )

    def test_post_reject_with_axis_and_comment_succeeds(self):
        self.client.force_login(self.trevor)
        response = self.client.post(
            self.url,
            {
                "verdict": Verdict.REJECT,
                "rejection_axis": RejectionAxis.ANCHOR,
                "comment": "anchor doesn't say this",
            },
        )
        self.assertEqual(response.status_code, 302)
        r = Response.objects.get(rule=self.rule, user=self.trevor)
        self.assertEqual(r.verdict, Verdict.REJECT)
        self.assertEqual(r.rejection_axis, RejectionAxis.ANCHOR)

    def test_post_revises_existing_response(self):
        Response.objects.create(
            rule=self.rule, user=self.trevor, verdict=Verdict.ACCEPT,
        )
        self.client.force_login(self.trevor)
        self.client.post(
            self.url,
            {
                "verdict": Verdict.REJECT,
                "rejection_axis": RejectionAxis.OVERALL,
                "comment": "changed my mind",
            },
        )
        # Still exactly one Response, but updated
        self.assertEqual(
            Response.objects.filter(rule=self.rule, user=self.trevor).count(),
            1,
        )
        r = Response.objects.get(rule=self.rule, user=self.trevor)
        self.assertEqual(r.verdict, Verdict.REJECT)

    def test_general_user_post_blocked(self):
        self.client.force_login(self.stranger)
        response = self.client.post(
            self.url,
            {"verdict": Verdict.ACCEPT},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Response.objects.filter(rule=self.rule).exists()
        )


class AdminQueueTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.master = Master.objects.create(slug="joe-pass", name="Joe Pass")
        self.admin = User.objects.create_user(
            username="dheeraj", is_staff=True,
            password=secrets.token_urlsafe(16),
        )
        self.trevor = _make_pedagogue("trevor")

    def test_general_user_403(self):
        self.client.force_login(self.trevor)
        response = self.client.get(reverse("rule_review:admin_queue"))
        self.assertEqual(response.status_code, 403)

    def test_admin_sees_queue_sorted_by_signal(self):
        # Rule A: 2 rejects, Rule B: 1 reject + 1 comment, Rule C: nothing
        rule_a = _make_rule(self.bundle, self.master, rule_id="A")
        rule_b = _make_rule(self.bundle, self.master, rule_id="B")
        rule_c = _make_rule(self.bundle, self.master, rule_id="C")
        other_pedagogue = _make_pedagogue("other")

        Response.objects.create(
            rule=rule_a, user=self.trevor, verdict=Verdict.REJECT,
            rejection_axis=RejectionAxis.ANCHOR, comment="x",
        )
        Response.objects.create(
            rule=rule_a, user=other_pedagogue, verdict=Verdict.REJECT,
            rejection_axis=RejectionAxis.ANCHOR, comment="y",
        )
        Response.objects.create(
            rule=rule_b, user=self.trevor, verdict=Verdict.REJECT,
            rejection_axis=RejectionAxis.WHEN, comment="z",
        )
        RuleComment.objects.create(
            rule=rule_b, author=self.trevor, body="discussion",
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse("rule_review:admin_queue"))
        self.assertEqual(response.status_code, 200)
        # Rule A has more rejects than B → A appears first
        body = response.content.decode()
        self.assertLess(body.find(rule_a.name), body.find(rule_b.name))
        # Rule C has no signal → not in queue
        self.assertNotIn(rule_c.name, body)


class CommentThreadTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.master = Master.objects.create(slug="joe-pass", name="Joe Pass")
        self.rule = _make_rule(self.bundle, self.master)
        self.trevor = _make_pedagogue("trevor")
        self.admin = User.objects.create_user(
            username="dheeraj", is_staff=True,
            password=secrets.token_urlsafe(16),
        )

    def test_pedagogue_can_post_comment(self):
        self.client.force_login(self.trevor)
        response = self.client.post(
            reverse("rule_review:add_rule_comment"),
            {"rule_id": self.rule.pk, "body": "interesting rule"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RuleComment.objects.count(), 1)

    def test_general_user_comment_blocked(self):
        general = User.objects.create_user(
            username="general1", password=secrets.token_urlsafe(16),
        )
        self.client.force_login(general)
        response = self.client.post(
            reverse("rule_review:add_rule_comment"),
            {"rule_id": self.rule.pk, "body": "x"},
        )
        self.assertEqual(response.status_code, 403)

    def test_author_can_delete_own_comment(self):
        c = RuleComment.objects.create(
            rule=self.rule, author=self.trevor, body="x",
        )
        self.client.force_login(self.trevor)
        response = self.client.post(
            reverse("rule_review:delete_rule_comment", args=[c.pk])
        )
        self.assertEqual(response.status_code, 302)
        c.refresh_from_db()
        self.assertIsNotNone(c.deleted_at)

    def test_admin_can_moderate_any_comment(self):
        c = RuleComment.objects.create(
            rule=self.rule, author=self.trevor, body="x",
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("rule_review:delete_rule_comment", args=[c.pk])
        )
        self.assertEqual(response.status_code, 302)
        c.refresh_from_db()
        self.assertIsNotNone(c.deleted_at)

    def test_threading_parent_resolution(self):
        parent = RuleComment.objects.create(
            rule=self.rule, author=self.trevor, body="parent",
        )
        self.client.force_login(self.trevor)
        self.client.post(
            reverse("rule_review:add_rule_comment"),
            {"rule_id": self.rule.pk, "body": "reply", "parent_id": parent.pk},
        )
        reply = RuleComment.objects.get(body="reply")
        self.assertEqual(reply.parent, parent)


class RuleLibraryViewTests(TestCase):
    """rule_library renders the locked formatter contract field set (#175)."""

    def setUp(self):
        self.bundle = _make_bundle()
        self.joe = Master.objects.create(slug="joe-pass", name="Joe Pass")
        self.ted = Master.objects.create(slug="ted-greene", name="Ted Greene")
        self.user = User.objects.create_user(
            username="general1", password=secrets.token_urlsafe(16),
        )
        self.rule_joe = _make_rule(
            self.bundle, self.joe,
            rule_id="joe-1",
            name="Voice the third on top for warmth",
            anchor="Always voice the major third on top.",
            source_page=42,
            applicability_reasons=["chord-melody", "warm-tone"],
            preference=2,
        )
        self.rule_ted = _make_rule(
            self.bundle, self.ted,
            rule_id="ted-1",
            name="Avoid root-position triads on downbeats",
            preference=-2,
            falsifier="A rule that fires across all four beats.",
        )

    def test_login_required(self):
        url = reverse("rule_review:rule_library")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_renders_grouped_by_master(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("rule_review:rule_library"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Joe Pass")
        self.assertContains(response, "Ted Greene")
        # Each rule's name renders
        self.assertContains(response, "Voice the third on top for warmth")
        self.assertContains(response, "Avoid root-position triads on downbeats")
        # Anchor + source-locator render
        self.assertContains(response, "Always voice the major third on top.")
        self.assertContains(response, "Page 42")
        # Applicability_reasons render as pills
        self.assertContains(response, "chord-melody")
        self.assertContains(response, "warm-tone")
        # Falsifier section present for the Ted rule
        self.assertContains(response, "fires across all four beats")
        # Preference Likert pill renders
        self.assertContains(response, '+2 recommend')
        self.assertContains(response, '-2 strong avoid')

    def test_master_filter_narrows(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("rule_review:rule_library") + "?master=joe-pass"
        )
        self.assertContains(response, "Joe Pass")
        self.assertNotContains(response, "Avoid root-position")

    def test_q_search_matches_anchor(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("rule_review:rule_library") + "?q=major third"
        )
        self.assertContains(response, "Voice the third on top")
        self.assertNotContains(response, "Avoid root-position triads")

    def test_q_search_no_match_renders_empty_state(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("rule_review:rule_library") + "?q=xyzzy-does-not-exist"
        )
        self.assertContains(response, "No rules match")

    def test_token_shape_in_context(self):
        """Sanity-check the structured token dict mirrors the locked contract."""
        from apps.rule_review.views import _rule_to_token

        token = _rule_to_token(self.rule_joe)
        self.assertEqual(token["source"], "rule")
        self.assertEqual(token["id"], self.rule_joe.pk)
        payload = token["payload"]
        # Required v1 + v2 fields per ellington-web#167 spec
        for field in (
            "rule_id", "master_id", "work_id", "name", "anchor",
            "source_page", "chapter_n", "section_title", "preference",
            "polarity", "quality_binding", "applicability_reasons",
            "falsifier",
        ):
            self.assertIn(field, payload, f"missing contract field {field!r}")
        self.assertEqual(payload["rule_id"], "joe-1")
        self.assertEqual(payload["master_id"], "joe-pass")
        self.assertIsNone(payload["chapter_n"])  # v2-reserved, model doesn't carry yet


# ---------------------------------------------------------------------------
# PedagogueConfirmation (#186 Phase 1)
# ---------------------------------------------------------------------------


class PedagogueConfirmationModelTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.master = Master.objects.create(slug="joe-pass", name="Joe Pass")
        self.rule = _make_rule(self.bundle, self.master)
        self.trevor = _make_pedagogue("trevor")

    def test_unique_per_rule_user(self):
        PedagogueConfirmation.objects.create(
            rule=self.rule, user=self.trevor, voicing_confirmed=True,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PedagogueConfirmation.objects.create(
                rule=self.rule, user=self.trevor, naming_confirmed=True,
            )

    def test_update_or_create_flow(self):
        PedagogueConfirmation.objects.update_or_create(
            rule=self.rule, user=self.trevor,
            defaults={"voicing_confirmed": True, "overall_confidence": 3},
        )
        obj, created = PedagogueConfirmation.objects.update_or_create(
            rule=self.rule, user=self.trevor,
            defaults={
                "voicing_confirmed": True,
                "naming_confirmed": True,
                "overall_confidence": 5,
            },
        )
        self.assertFalse(created)
        self.assertTrue(obj.naming_confirmed)
        self.assertEqual(obj.overall_confidence, 5)
        self.assertEqual(
            PedagogueConfirmation.objects.filter(rule=self.rule).count(), 1,
        )

    def test_confidence_range_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PedagogueConfirmation.objects.create(
                rule=self.rule, user=self.trevor, overall_confidence=6,
            )

    def test_confidence_null_allowed(self):
        obj = PedagogueConfirmation.objects.create(
            rule=self.rule, user=self.trevor, overall_confidence=None,
        )
        self.assertIsNone(obj.overall_confidence)


class ConfirmRuleViewTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.master = Master.objects.create(slug="joe-pass", name="Joe Pass")
        self.rule = _make_rule(self.bundle, self.master)
        self.trevor = _make_pedagogue("trevor")
        self.stranger = User.objects.create_user(
            username="stranger", password=secrets.token_urlsafe(16),
        )

    def _url(self):
        return reverse("rule_review:confirm_rule", args=[self.rule.pk])

    def test_login_required(self):
        response = self.client.post(self._url(), {})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.url)

    def test_pedagogue_only_write(self):
        self.client.force_login(self.stranger)
        response = self.client.post(self._url(), {"voicing_confirmed": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            PedagogueConfirmation.objects.filter(rule=self.rule).exists(),
        )

    def test_persists_all_axes(self):
        self.client.force_login(self.trevor)
        response = self.client.post(self._url(), {
            "voicing_confirmed": "1",
            "voicing_note": "matches CAGED shape III",
            "naming_confirmed": "1",
            "lesson_confirmed": "",
            "lesson_note": "anchor only weakly supports",
            "overall_confidence": "4",
        })
        self.assertEqual(response.status_code, 302)
        obj = PedagogueConfirmation.objects.get(rule=self.rule, user=self.trevor)
        self.assertTrue(obj.voicing_confirmed)
        self.assertTrue(obj.naming_confirmed)
        self.assertFalse(obj.lesson_confirmed)
        self.assertEqual(obj.voicing_note, "matches CAGED shape III")
        self.assertEqual(obj.lesson_note, "anchor only weakly supports")
        self.assertEqual(obj.overall_confidence, 4)

    def test_update_or_create_revises(self):
        self.client.force_login(self.trevor)
        self.client.post(self._url(), {
            "voicing_confirmed": "1", "overall_confidence": "2",
        })
        self.client.post(self._url(), {
            "voicing_confirmed": "1",
            "naming_confirmed": "1",
            "overall_confidence": "5",
        })
        objs = PedagogueConfirmation.objects.filter(rule=self.rule)
        self.assertEqual(objs.count(), 1)
        obj = objs.get()
        self.assertTrue(obj.naming_confirmed)
        self.assertEqual(obj.overall_confidence, 5)

    def test_blank_confidence_persists_null(self):
        self.client.force_login(self.trevor)
        self.client.post(self._url(), {
            "voicing_confirmed": "1", "overall_confidence": "",
        })
        obj = PedagogueConfirmation.objects.get(rule=self.rule, user=self.trevor)
        self.assertIsNone(obj.overall_confidence)

    def test_out_of_range_confidence_rejected(self):
        self.client.force_login(self.trevor)
        self.client.post(self._url(), {"overall_confidence": "9"})
        self.assertFalse(
            PedagogueConfirmation.objects.filter(rule=self.rule).exists(),
        )


# ---------------------------------------------------------------------------
# Confirmation queue (#186 Phase 3)
# ---------------------------------------------------------------------------


class ConfirmationQueueViewTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.master = Master.objects.create(slug="joe-pass", name="Joe Pass")
        self.rule_a = _make_rule(
            self.bundle, self.master,
            work_id="w1", rule_id="r-a", name="rule A",
        )
        self.rule_b = _make_rule(
            self.bundle, self.master,
            work_id="w1", rule_id="r-b", name="rule B",
        )
        self.rule_untouched = _make_rule(
            self.bundle, self.master,
            work_id="w1", rule_id="r-z", name="rule untouched",
        )
        self.ped_a = _make_pedagogue("alpha")
        self.ped_b = _make_pedagogue("beta")
        self.ped_c = _make_pedagogue("gamma")
        self.admin = User.objects.create_user(
            username="admin", password=secrets.token_urlsafe(16),
            is_staff=True,
        )
        self.stranger = User.objects.create_user(
            username="stranger", password=secrets.token_urlsafe(16),
        )

        # rule_a: high confidence, all-yes on voicing+naming+lesson
        PedagogueConfirmation.objects.create(
            rule=self.rule_a, user=self.ped_a,
            voicing_confirmed=True, naming_confirmed=True, lesson_confirmed=True,
            overall_confidence=5,
        )
        PedagogueConfirmation.objects.create(
            rule=self.rule_a, user=self.ped_b,
            voicing_confirmed=True, naming_confirmed=True, lesson_confirmed=True,
            overall_confidence=5,
        )

        # rule_b: lower confidence, voicing disagreement
        PedagogueConfirmation.objects.create(
            rule=self.rule_b, user=self.ped_a,
            voicing_confirmed=True, naming_confirmed=False, lesson_confirmed=False,
            overall_confidence=2,
        )
        PedagogueConfirmation.objects.create(
            rule=self.rule_b, user=self.ped_b,
            voicing_confirmed=False, naming_confirmed=False, lesson_confirmed=True,
            overall_confidence=3,
        )
        PedagogueConfirmation.objects.create(
            rule=self.rule_b, user=self.ped_c,
            voicing_confirmed=True, naming_confirmed=False, lesson_confirmed=True,
            overall_confidence=None,
        )
        # rule_untouched has no confirmations — should never appear

    def test_admin_only(self):
        self.client.force_login(self.stranger)
        response = self.client.get(reverse("rule_review:confirmation_queue"))
        self.assertEqual(response.status_code, 403)

    def test_excludes_untouched_rules(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("rule_review:confirmation_queue"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "rule untouched")

    def test_lowest_confidence_sort_default(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("rule_review:confirmation_queue"))
        # rule_b avg = (2+3)/2 = 2.5 (NULL ignored); rule_a avg = 5
        # Lowest-confidence default puts B before A.
        rules = list(response.context["page_obj"].object_list)
        names = [r.name for r in rules]
        self.assertEqual(names.index("rule B") < names.index("rule A"), True)

    def test_voicing_disagreement_sort(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("rule_review:confirmation_queue")
            + "?sort=most_voicing_disagreement"
        )
        # rule_a has no voicing_no, so it's filtered out of this sort
        rules = list(response.context["page_obj"].object_list)
        names = [r.name for r in rules]
        self.assertIn("rule B", names)
        self.assertNotIn("rule A", names)

    def test_axis_filter_voicing(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("rule_review:confirmation_queue") + "?axis=voicing"
        )
        rules = list(response.context["page_obj"].object_list)
        # Both rules touched the voicing axis
        names = [r.name for r in rules]
        self.assertIn("rule A", names)
        self.assertIn("rule B", names)

    def test_invalid_sort_falls_back_to_default(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("rule_review:confirmation_queue") + "?sort=garbage"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["filter_sort"], "lowest_confidence")

    def test_annotations_present(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("rule_review:confirmation_queue"))
        rule_b = next(
            r for r in response.context["page_obj"].object_list
            if r.name == "rule B"
        )
        self.assertEqual(rule_b.voicing_yes, 2)
        self.assertEqual(rule_b.voicing_no, 1)
        self.assertEqual(rule_b.naming_yes, 0)
        self.assertEqual(rule_b.naming_no, 3)
        self.assertEqual(rule_b.confirmation_count, 3)
