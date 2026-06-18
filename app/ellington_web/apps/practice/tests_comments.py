"""Tests for Recording comments (epic #96 sub-ticket d / #110)."""

from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.charts.models import Song, Songbook
from apps.practice.models import (
    PracticeSession,
    Recording,
    RecordingComment,
    RecordingShare,
)
from apps.practice.permissions import (
    can_access_recording,
    is_recording_owner,
)
from apps.styles.models import StylePreset


User = get_user_model()


def _make_recording(owner) -> Recording:
    songbook = Songbook.objects.create(title="t")
    song = Song.objects.create(title="Song", songbook=songbook)
    preset = StylePreset.objects.create(slug=f"p-{secrets.token_hex(4)}", name="P")
    session = PracticeSession.objects.create(
        user=owner, song=song, target_preset=preset, tempo_bpm=120,
    )
    return Recording.objects.create(session=session, file_ref="x.wav")


class PermissionHelperTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        self.eve = User.objects.create_user(
            username="eve", password=secrets.token_urlsafe(16),
        )
        self.recording = _make_recording(self.alice)
        RecordingShare.objects.create(
            recording=self.recording, sharer=self.alice, recipient=self.bob,
        )

    def test_owner_can_access(self):
        self.assertTrue(can_access_recording(self.alice, self.recording))

    def test_share_recipient_can_access(self):
        self.assertTrue(can_access_recording(self.bob, self.recording))

    def test_stranger_cannot_access(self):
        self.assertFalse(can_access_recording(self.eve, self.recording))

    def test_anonymous_cannot_access(self):
        self.assertFalse(can_access_recording(None, self.recording))

    def test_owner_predicate(self):
        self.assertTrue(is_recording_owner(self.alice, self.recording))
        self.assertFalse(is_recording_owner(self.bob, self.recording))


class AddCommentTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        self.eve = User.objects.create_user(
            username="eve", password=secrets.token_urlsafe(16),
        )
        self.recording = _make_recording(self.alice)
        self.recording.duration_ms = 60_000
        self.recording.save(update_fields=["duration_ms"])
        RecordingShare.objects.create(
            recording=self.recording, sharer=self.alice, recipient=self.bob,
        )
        self.url = reverse(
            "practice:add_recording_comment", args=[self.recording.pk],
        )

    def test_owner_can_comment(self):
        self.client.force_login(self.alice)
        response = self.client.post(self.url, {"body": "great take"})
        self.assertEqual(response.status_code, 302)
        comment = RecordingComment.objects.get()
        self.assertEqual(comment.author, self.alice)
        self.assertEqual(comment.body, "great take")

    def test_share_recipient_can_comment(self):
        self.client.force_login(self.bob)
        response = self.client.post(self.url, {"body": "nice line on bar 8"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RecordingComment.objects.get().author, self.bob)

    def test_stranger_gets_403(self):
        self.client.force_login(self.eve)
        response = self.client.post(self.url, {"body": "intruder"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(RecordingComment.objects.count(), 0)

    def test_anonymous_redirects_to_login(self):
        response = self.client.post(self.url, {"body": "hi"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_empty_body_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(self.url, {"body": "   "})
        self.assertEqual(response.status_code, 302)  # redirect with messages
        self.assertEqual(RecordingComment.objects.count(), 0)

    def test_anchor_ms_validates_against_duration(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            self.url, {"body": "x", "anchor_ms": "999999"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RecordingComment.objects.count(), 0)

    def test_valid_anchor_ms_persists(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            self.url, {"body": "x", "anchor_ms": "12500"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RecordingComment.objects.get().anchor_ms, 12500)

    def test_threading_parent_id(self):
        parent = RecordingComment.objects.create(
            recording=self.recording, author=self.alice, body="parent",
        )
        self.client.force_login(self.bob)
        response = self.client.post(
            self.url, {"body": "reply", "parent_id": str(parent.pk)},
        )
        self.assertEqual(response.status_code, 302)
        reply = RecordingComment.objects.get(body="reply")
        self.assertEqual(reply.parent, parent)


class DeleteCommentTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        self.eve = User.objects.create_user(
            username="eve", password=secrets.token_urlsafe(16),
        )
        self.recording = _make_recording(self.alice)
        RecordingShare.objects.create(
            recording=self.recording, sharer=self.alice, recipient=self.bob,
        )
        self.bob_comment = RecordingComment.objects.create(
            recording=self.recording, author=self.bob, body="bob's comment",
        )

    def test_author_can_delete_own_comment(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse(
                "practice:delete_recording_comment",
                args=[self.bob_comment.pk],
            )
        )
        self.assertEqual(response.status_code, 302)
        self.bob_comment.refresh_from_db()
        self.assertIsNotNone(self.bob_comment.deleted_at)
        self.assertEqual(self.bob_comment.display_body, "[deleted]")

    def test_recording_owner_can_moderate_anyones_comment(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse(
                "practice:delete_recording_comment",
                args=[self.bob_comment.pk],
            )
        )
        self.assertEqual(response.status_code, 302)
        self.bob_comment.refresh_from_db()
        self.assertIsNotNone(self.bob_comment.deleted_at)

    def test_stranger_cannot_delete(self):
        # Eve has no share, no ownership
        self.client.force_login(self.eve)
        response = self.client.post(
            reverse(
                "practice:delete_recording_comment",
                args=[self.bob_comment.pk],
            )
        )
        self.assertEqual(response.status_code, 403)
        self.bob_comment.refresh_from_db()
        self.assertIsNone(self.bob_comment.deleted_at)


class EditCommentTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        self.recording = _make_recording(self.alice)
        self.bob_comment = RecordingComment.objects.create(
            recording=self.recording, author=self.bob, body="original",
        )

    def test_author_can_edit_own_body(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse(
                "practice:edit_recording_comment",
                args=[self.bob_comment.pk],
            ),
            {"body": "edited"},
        )
        self.assertEqual(response.status_code, 302)
        self.bob_comment.refresh_from_db()
        self.assertEqual(self.bob_comment.body, "edited")
        self.assertIsNotNone(self.bob_comment.edited_at)

    def test_non_author_cannot_edit(self):
        self.client.force_login(self.alice)  # owner but NOT author
        response = self.client.post(
            reverse(
                "practice:edit_recording_comment",
                args=[self.bob_comment.pk],
            ),
            {"body": "hijacked"},
        )
        self.assertEqual(response.status_code, 403)
        self.bob_comment.refresh_from_db()
        self.assertEqual(self.bob_comment.body, "original")

    def test_cannot_edit_deleted_comment(self):
        from django.utils import timezone

        self.bob_comment.deleted_at = timezone.now()
        self.bob_comment.save(update_fields=["deleted_at"])
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse(
                "practice:edit_recording_comment",
                args=[self.bob_comment.pk],
            ),
            {"body": "x"},
        )
        self.assertEqual(response.status_code, 410)
