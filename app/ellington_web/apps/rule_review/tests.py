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
