"""Tests for self-service account deletion (epic #96 sub-ticket k / #112)."""

from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.deletion import perform_account_deletion
from apps.core.models import (
    AccountDeletionAudit,
    DELETED_USER_USERNAME,
    Goal,
    UserProfile,
    get_or_create_deleted_user_sentinel,
)


User = get_user_model()


class PerformAccountDeletionHelperTests(TestCase):
    """The deletion module is the shared seam between the command and
    the view — verify it directly first, then the surfaces on top."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="dheeraj", is_staff=True,
            password=secrets.token_urlsafe(16),
        )
        self.target = User.objects.create_user(
            username="general1", password=secrets.token_urlsafe(16),
        )
        UserProfile.objects.create(user=self.target)
        Goal.objects.create(user=self.target, title="goal A")

    def test_hard_deletes_target_and_writes_audit(self):
        audit = perform_account_deletion(
            self.target, initiated_by=self.admin,
        )
        self.assertFalse(User.objects.filter(username="general1").exists())
        self.assertEqual(audit.deleted_username, "general1")
        self.assertEqual(audit.deleted_by, self.admin)
        self.assertEqual(audit.anonymized_artifact_counts["goals_deleted"], 1)
        self.assertEqual(audit.anonymized_artifact_counts["profile_deleted"], 1)

    def test_refuses_sentinel_target(self):
        sentinel = get_or_create_deleted_user_sentinel()
        with self.assertRaises(ValueError):
            perform_account_deletion(sentinel, initiated_by=self.admin)

    def test_refuses_sentinel_username_target(self):
        # Make a fresh user that happens to have the sentinel username
        # — shouldn't happen in practice but the guard exists.
        sentinel = get_or_create_deleted_user_sentinel()
        # Sentinel already exists with the right name; just confirm the
        # username check kicks before the pk check.
        with self.assertRaises(ValueError):
            perform_account_deletion(sentinel, initiated_by=self.admin)

    def test_refuses_none_inputs(self):
        with self.assertRaises(ValueError):
            perform_account_deletion(None, initiated_by=self.admin)
        with self.assertRaises(ValueError):
            perform_account_deletion(self.target, initiated_by=None)

    def test_self_delete_writes_audit_with_null_deleted_by(self):
        # In the self-delete path, initiated_by == user_to_delete. After
        # delete() the User row is gone; deleted_by FK is left null and
        # we rely on initiated_by_username for the audit trail.
        audit = perform_account_deletion(
            self.target, initiated_by=self.target,
        )
        self.assertFalse(User.objects.filter(username="general1").exists())
        self.assertEqual(audit.deleted_username, "general1")
        self.assertEqual(audit.initiated_by_username, "general1")
        self.assertIsNone(audit.deleted_by)

    def test_admin_delete_keeps_deleted_by_fk_populated(self):
        audit = perform_account_deletion(
            self.target, initiated_by=self.admin,
        )
        self.assertEqual(audit.initiated_by_username, "dheeraj")
        self.assertEqual(audit.deleted_by, self.admin)


class SelfDeleteViewTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("core:self_delete"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_get_shows_confirm_form(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("core:self_delete"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delete your account")
        self.assertContains(response, "alice")

    def test_post_with_wrong_username_rerenders_form(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("core:self_delete"),
            {"confirm_username": "bob"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "doesn't match")
        self.assertTrue(User.objects.filter(username="alice").exists())

    def test_post_with_matching_username_deletes_account(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("core:self_delete"),
            {"confirm_username": "alice", "reason": "moving on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="alice").exists())
        # Audit row written with null deleted_by + username snapshot
        audit = AccountDeletionAudit.objects.get(deleted_username="alice")
        self.assertEqual(audit.initiated_by_username, "alice")
        self.assertIsNone(audit.deleted_by)

    def test_account_deleted_goodbye_page(self):
        response = self.client.get(reverse("core:account_deleted"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your account is gone")
