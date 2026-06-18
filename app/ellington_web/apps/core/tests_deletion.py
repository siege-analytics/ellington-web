"""Tests for delete_user_account command + sentinel-user mechanics.

Covers the four required behaviors:
- Hard-deletes Goals + UserProfile (cascade)
- Anonymizes registered artifacts to the sentinel
- Writes AccountDeletionAudit with non-empty admin FK + counts
- Refuses if --initiated-by is not staff or is missing
- Refuses to delete the sentinel itself
"""

from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.core.models import (
    AccountDeletionAudit,
    DELETED_USER_USERNAME,
    Goal,
    UserProfile,
    get_or_create_deleted_user_sentinel,
)
from apps.core.management.commands import delete_user_account as cmd_module


User = get_user_model()


class SentinelTests(TestCase):
    def test_sentinel_creation_is_idempotent(self):
        s1 = get_or_create_deleted_user_sentinel()
        s2 = get_or_create_deleted_user_sentinel()
        self.assertEqual(s1.pk, s2.pk)
        self.assertEqual(s1.username, DELETED_USER_USERNAME)

    def test_sentinel_cannot_log_in(self):
        s = get_or_create_deleted_user_sentinel()
        self.assertFalse(s.is_active)
        self.assertFalse(s.has_usable_password())


class DeleteUserAccountTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create(username="dheeraj", is_staff=True)
        self.target = User.objects.create(username="general1")
        UserProfile.objects.create(user=self.target)
        Goal.objects.create(user=self.target, title="goal A")
        Goal.objects.create(user=self.target, title="goal B")

    def test_hard_deletes_goals_and_profile(self):
        call_command(
            "delete_user_account",
            "general1",
            "--initiated-by", "dheeraj",
            stdout=StringIO(),
        )
        self.assertFalse(User.objects.filter(username="general1").exists())
        self.assertEqual(Goal.objects.filter(user__username="general1").count(), 0)
        self.assertEqual(UserProfile.objects.filter(user__username="general1").count(), 0)

    def test_writes_audit_row(self):
        call_command(
            "delete_user_account",
            "general1",
            "--initiated-by", "dheeraj",
            stdout=StringIO(),
        )
        audits = list(AccountDeletionAudit.objects.all())
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.deleted_username, "general1")
        self.assertEqual(audit.deleted_by.username, "dheeraj")
        self.assertEqual(audit.anonymized_artifact_counts["goals_deleted"], 2)
        self.assertEqual(audit.anonymized_artifact_counts["profile_deleted"], 1)

    def test_refuses_non_staff_initiator(self):
        User.objects.create(username="not_admin")
        with self.assertRaises(CommandError):
            call_command(
                "delete_user_account",
                "general1",
                "--initiated-by", "not_admin",
                stdout=StringIO(),
            )
        # Target survives — transaction rolled back
        self.assertTrue(User.objects.filter(username="general1").exists())

    def test_refuses_unknown_target(self):
        with self.assertRaises(CommandError):
            call_command(
                "delete_user_account",
                "nope",
                "--initiated-by", "dheeraj",
                stdout=StringIO(),
            )

    def test_refuses_to_delete_sentinel(self):
        get_or_create_deleted_user_sentinel()
        with self.assertRaises(CommandError):
            call_command(
                "delete_user_account",
                DELETED_USER_USERNAME,
                "--initiated-by", "dheeraj",
                stdout=StringIO(),
            )


class AnonymizeRegistryTests(TestCase):
    """The ANONYMIZE_REGISTRY is empty in v1 but exercised via a test
    callback to verify the wiring sub-tickets (d) and #98 will use."""

    def setUp(self):
        self.admin = User.objects.create(username="dheeraj", is_staff=True)
        self.target = User.objects.create(username="general2")

    def tearDown(self):
        cmd_module.ANONYMIZE_REGISTRY.clear()

    def test_registered_callback_runs_and_count_lands_in_audit(self):
        calls = {"n": 0}

        def fake_repoint(user, sentinel):
            # Sub-ticket (d) Comment.author.repoint(...) shape.
            calls["n"] += 1
            self.assertEqual(user.username, "general2")
            self.assertEqual(sentinel.username, DELETED_USER_USERNAME)
            return 7

        cmd_module.ANONYMIZE_REGISTRY.append(("comments_anonymized", fake_repoint))

        call_command(
            "delete_user_account",
            "general2",
            "--initiated-by", "dheeraj",
            stdout=StringIO(),
        )

        self.assertEqual(calls["n"], 1)
        audit = AccountDeletionAudit.objects.get(deleted_username="general2")
        self.assertEqual(audit.anonymized_artifact_counts["comments_anonymized"], 7)
