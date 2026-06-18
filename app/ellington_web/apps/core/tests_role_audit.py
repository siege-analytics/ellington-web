"""Tests for RolePromotionAudit + signal wiring (epic #96 sub-ticket j / #131)."""

from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from apps.core.middleware import CurrentUserMiddleware, get_current_user
from apps.core.models import RolePromotionAudit, UserProfile


User = get_user_model()


class CurrentUserMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )

    def test_middleware_stashes_and_clears(self):
        captured = []

        def view(request):
            captured.append(get_current_user())
            return None  # response not used

        middleware = CurrentUserMiddleware(view)
        request = self.factory.get("/")
        request.user = self.alice
        middleware(request)

        self.assertEqual(captured[0], self.alice)
        self.assertIsNone(get_current_user())


class RolePromotionAuditSignalTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="dheeraj", is_staff=True,
            password=secrets.token_urlsafe(16),
        )
        self.trevor = User.objects.create_user(
            username="trevor", password=secrets.token_urlsafe(16),
        )
        self.profile = UserProfile.objects.create(
            user=self.trevor, is_pedagogue=False,
        )

    def test_no_audit_on_initial_create(self):
        # Created in setUp — no audit should exist for that creation
        self.assertEqual(RolePromotionAudit.objects.count(), 0)

    def test_audit_written_on_pedagogue_flip(self):
        # Reload from DB to populate _initial_role_values
        profile = UserProfile.objects.get(pk=self.profile.pk)
        profile.is_pedagogue = True
        profile.save()

        audit = RolePromotionAudit.objects.get()
        self.assertEqual(audit.target_user, self.trevor)
        self.assertEqual(audit.target_username, "trevor")
        self.assertEqual(audit.field_name, "is_pedagogue")
        self.assertFalse(audit.old_value)
        self.assertTrue(audit.new_value)

    def test_audit_records_system_when_no_request_user(self):
        profile = UserProfile.objects.get(pk=self.profile.pk)
        profile.is_pedagogue = True
        profile.save()
        audit = RolePromotionAudit.objects.get()
        # No middleware in test path, so promoted_by is None and
        # promoted_by_username is 'system'
        self.assertIsNone(audit.promoted_by)
        self.assertEqual(audit.promoted_by_username, "system")

    def test_no_audit_when_unrelated_field_changes(self):
        profile = UserProfile.objects.get(pk=self.profile.pk)
        profile.bio = "new bio"
        profile.save()
        self.assertEqual(RolePromotionAudit.objects.count(), 0)

    def test_consecutive_flips_record_separately(self):
        profile = UserProfile.objects.get(pk=self.profile.pk)
        profile.is_pedagogue = True
        profile.save()
        profile.is_pedagogue = False
        profile.save()
        audits = list(RolePromotionAudit.objects.order_by("promoted_at"))
        self.assertEqual(len(audits), 2)
        self.assertTrue(audits[0].new_value)
        self.assertFalse(audits[1].new_value)
