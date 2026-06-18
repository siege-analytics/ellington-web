"""Tests for Recording sharing + invite-a-friend (epic #96 sub-ticket b / #108).

Covers:
- Share form: existing-user path creates RecordingShare, no Invite
- Share form: outsider path creates Invite + RecordingShare(recipient=null)
- Share form: rejects sharing with self
- Share form: rejects both fields blank or both filled
- Owner-only on share form (404 for non-owner)
- Login-required on share form + shared-with-me
- shared_with_me only lists incoming shares for signed-in user
- Invite acceptance: signup creates user, redeems invite, backfills shares
- Invite acceptance: expired token → 410
- Invite acceptance: redeemed token → 410
- Invite acceptance: unknown token → 410
- Invite signup: password mismatch rejected
- Invite signup: duplicate username rejected
- Email is sent on both share paths (invite + in-system notify)
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.charts.models import Song, Songbook
from apps.practice.models import (
    Invite,
    PracticeSession,
    Recording,
    RecordingShare,
)
from apps.styles.models import StylePreset


User = get_user_model()


def _make_recording(owner) -> Recording:
    """Spin up a minimal PracticeSession + Recording owned by ``owner``."""
    songbook = Songbook.objects.create(title="t")
    song = Song.objects.create(title="Song", songbook=songbook)
    preset = StylePreset.objects.create(slug=f"p-{secrets.token_hex(4)}", name="P")
    session = PracticeSession.objects.create(
        user=owner,
        song=song,
        target_preset=preset,
        tempo_bpm=120,
    )
    return Recording.objects.create(session=session, file_ref="x.wav")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ShareToExistingUserTests(TestCase):
    def setUp(self):
        mail.outbox = []
        self.alice = User.objects.create_user(
            username="alice", email="alice@example.com",
            password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", email="bob@example.com",
            password=secrets.token_urlsafe(16),
        )
        self.recording = _make_recording(self.alice)

    def test_share_to_existing_user_by_email(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("practice:share_recording", args=[self.recording.pk]),
            {"recipient_lookup": "bob@example.com", "share_note": "listen to this"},
        )
        self.assertEqual(response.status_code, 302)
        share = RecordingShare.objects.get()
        self.assertEqual(share.sharer, self.alice)
        self.assertEqual(share.recipient, self.bob)
        self.assertIsNone(share.invite)
        self.assertEqual(share.share_note, "listen to this")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.bob.email])

    def test_share_to_existing_user_by_username(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("practice:share_recording", args=[self.recording.pk]),
            {"recipient_lookup": "bob"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RecordingShare.objects.get().recipient, self.bob)

    def test_share_with_self_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("practice:share_recording", args=[self.recording.pk]),
            {"recipient_lookup": "alice"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "yourself")
        self.assertEqual(RecordingShare.objects.count(), 0)

    def test_share_form_rejects_both_blank(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("practice:share_recording", args=[self.recording.pk]),
            {},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "existing user OR")

    def test_share_form_rejects_both_filled(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("practice:share_recording", args=[self.recording.pk]),
            {"recipient_lookup": "bob", "recipient_email": "x@x.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not both")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ShareToOutsiderInviteTests(TestCase):
    def setUp(self):
        mail.outbox = []
        self.alice = User.objects.create_user(
            username="alice", email="alice@example.com",
            password=secrets.token_urlsafe(16),
        )
        self.recording = _make_recording(self.alice)

    def test_outsider_share_creates_invite_and_pending_share(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("practice:share_recording", args=[self.recording.pk]),
            {
                "recipient_email": "outsider@example.com",
                "recipient_name": "Outsider",
                "share_note": "we should jam",
            },
        )
        self.assertEqual(response.status_code, 302)
        invite = Invite.objects.get()
        self.assertEqual(invite.email, "outsider@example.com")
        self.assertEqual(invite.inviter, self.alice)
        self.assertFalse(invite.is_redeemed)
        self.assertGreater(invite.expires_at, timezone.now())
        share = RecordingShare.objects.get()
        self.assertIsNone(share.recipient)
        self.assertEqual(share.invite, invite)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["outsider@example.com"])


class ShareFormOwnerCheckTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        self.recording = _make_recording(self.alice)

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(
            reverse("practice:share_recording", args=[self.recording.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_non_owner_gets_404(self):
        self.client.force_login(self.bob)
        response = self.client.get(
            reverse("practice:share_recording", args=[self.recording.pk])
        )
        self.assertEqual(response.status_code, 404)


class SharedWithMeTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        rec_a = _make_recording(self.alice)
        rec_b = _make_recording(self.bob)
        RecordingShare.objects.create(
            recording=rec_a, sharer=self.alice, recipient=self.bob,
        )
        RecordingShare.objects.create(
            recording=rec_b, sharer=self.bob, recipient=self.alice,
        )

    def test_shared_with_me_only_lists_incoming_for_signed_in_user(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("practice:shared_with_me"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["shares"]), 1)
        self.assertEqual(response.context["shares"][0].sharer, self.bob)

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("practice:shared_with_me"))
        self.assertEqual(response.status_code, 302)


class InviteAcceptanceTests(TestCase):
    def setUp(self):
        mail.outbox = []
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.recording = _make_recording(self.alice)
        self.invite = Invite.objects.create(
            token=secrets.token_urlsafe(32),
            inviter=self.alice,
            email="outsider@example.com",
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.share = RecordingShare.objects.create(
            recording=self.recording,
            sharer=self.alice,
            invite=self.invite,
        )

    def test_get_shows_signup_form_for_valid_token(self):
        response = self.client.get(
            reverse("core:accept_invite", args=[self.invite.token])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome to Ellington")
        self.assertContains(response, "alice")

    def test_post_signup_creates_user_and_redeems_invite(self):
        token = self.invite.token
        password = secrets.token_urlsafe(16)
        response = self.client.post(
            reverse("core:accept_invite", args=[token]),
            {
                "username": "outsider",
                "password1": password,
                "password2": password,
            },
        )
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(username="outsider")
        self.assertEqual(user.email, "outsider@example.com")
        self.invite.refresh_from_db()
        self.assertTrue(self.invite.is_redeemed)
        self.assertEqual(self.invite.redeemed_by, user)
        self.share.refresh_from_db()
        self.assertEqual(self.share.recipient, user)
        self.assertIsNone(self.share.invite)

    def test_unknown_token_returns_410(self):
        response = self.client.get(
            reverse("core:accept_invite", args=["bogus-token-not-in-db"])
        )
        self.assertEqual(response.status_code, 410)

    def test_expired_token_returns_410(self):
        self.invite.expires_at = timezone.now() - timedelta(days=1)
        self.invite.save(update_fields=["expires_at"])
        response = self.client.get(
            reverse("core:accept_invite", args=[self.invite.token])
        )
        self.assertEqual(response.status_code, 410)

    def test_already_redeemed_token_returns_410(self):
        other = User.objects.create_user(
            username="other", password=secrets.token_urlsafe(16),
        )
        self.invite.accepted_at = timezone.now()
        self.invite.redeemed_by = other
        self.invite.save(update_fields=["accepted_at", "redeemed_by"])
        response = self.client.get(
            reverse("core:accept_invite", args=[self.invite.token])
        )
        self.assertEqual(response.status_code, 410)

    def test_password_mismatch_rejected(self):
        response = self.client.post(
            reverse("core:accept_invite", args=[self.invite.token]),
            {
                "username": "outsider",
                "password1": "abcdefgh1!",
                "password2": "different1!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "passwords don")
        self.assertFalse(User.objects.filter(username="outsider").exists())

    def test_duplicate_username_rejected(self):
        User.objects.create_user(
            username="outsider", password=secrets.token_urlsafe(16),
        )
        password = secrets.token_urlsafe(16)
        response = self.client.post(
            reverse("core:accept_invite", args=[self.invite.token]),
            {
                "username": "outsider",
                "password1": password,
                "password2": password,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "taken")
        self.invite.refresh_from_db()
        self.assertFalse(self.invite.is_redeemed)
