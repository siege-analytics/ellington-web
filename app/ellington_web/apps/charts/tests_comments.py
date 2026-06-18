"""Tests for chart comments (epic #96 sub-ticket e / #114)."""

from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.charts.models import (
    ChartComment,
    ChordEvent,
    Measure,
    Section,
    Song,
    Songbook,
)
from apps.core.models import UserProfile


User = get_user_model()


def _make_song_chord_event():
    songbook = Songbook.objects.create(title="t")
    song = Song.objects.create(title="Song", songbook=songbook)
    section = Section.objects.create(
        song=song, label="A", order_index=0,
    )
    measure = Measure.objects.create(section=section, number_in_section=1)
    chord_event = ChordEvent.objects.create(
        measure=measure, beat=1, chord_symbol="Cmaj7",
    )
    return song, section, chord_event


class AnchorConstraintTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.song, self.section, self.chord_event = _make_song_chord_event()

    def test_can_anchor_to_song(self):
        comment = ChartComment.objects.create(
            song=self.song, author=self.alice, body="whole-song",
        )
        self.assertEqual(str(ChartComment.objects.get(pk=comment.pk).song_id),
                         str(self.song.pk))

    def test_can_anchor_to_section(self):
        ChartComment.objects.create(
            section=self.section, author=self.alice, body="section",
        )
        self.assertEqual(ChartComment.objects.filter(section=self.section).count(), 1)

    def test_can_anchor_to_chord_event(self):
        ChartComment.objects.create(
            chord_event=self.chord_event, author=self.alice, body="chord",
        )
        self.assertEqual(
            ChartComment.objects.filter(chord_event=self.chord_event).count(), 1,
        )

    def test_cannot_anchor_to_none(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ChartComment.objects.create(author=self.alice, body="no-anchor")

    def test_cannot_anchor_to_two(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ChartComment.objects.create(
                song=self.song, section=self.section,
                author=self.alice, body="both",
            )


class AddCommentViewTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.song, self.section, self.chord_event = _make_song_chord_event()
        self.url = reverse("charts:add_chart_comment")

    def test_login_required(self):
        response = self.client.post(self.url, {
            "song_id": self.song.pk, "body": "x",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_authenticated_user_can_comment_on_song(self):
        self.client.force_login(self.alice)
        response = self.client.post(self.url, {
            "song_id": self.song.pk, "body": "great chart",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ChartComment.objects.count(), 1)
        self.assertEqual(ChartComment.objects.get().body, "great chart")

    def test_empty_body_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(self.url, {
            "song_id": self.song.pk, "body": "   ",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ChartComment.objects.count(), 0)

    def test_no_anchor_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(self.url, {"body": "no anchor"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ChartComment.objects.count(), 0)

    def test_multiple_anchors_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(self.url, {
            "song_id": self.song.pk,
            "section_id": self.section.pk,
            "body": "both",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ChartComment.objects.count(), 0)

    def test_threading_parent_must_share_anchor(self):
        self.client.force_login(self.alice)
        parent = ChartComment.objects.create(
            song=self.song, author=self.alice, body="parent on song",
        )
        # parent matches song → reply lands
        response = self.client.post(self.url, {
            "song_id": self.song.pk,
            "body": "reply",
            "parent_id": str(parent.pk),
        })
        self.assertEqual(response.status_code, 302)
        reply = ChartComment.objects.get(body="reply")
        self.assertEqual(reply.parent, parent)

        # parent has song anchor but reply is to section → parent
        # lookup fails and reply lands at top level
        response = self.client.post(self.url, {
            "section_id": self.section.pk,
            "body": "wrong-anchor-reply",
            "parent_id": str(parent.pk),
        })
        wrong = ChartComment.objects.get(body="wrong-anchor-reply")
        self.assertIsNone(wrong.parent)


class DeleteCommentTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        self.admin = User.objects.create_user(
            username="admin", is_staff=True,
            password=secrets.token_urlsafe(16),
        )
        self.pedagogue = User.objects.create_user(
            username="ped", password=secrets.token_urlsafe(16),
        )
        UserProfile.objects.create(user=self.pedagogue, is_pedagogue=True)

        self.song, _, _ = _make_song_chord_event()
        self.comment = ChartComment.objects.create(
            song=self.song, author=self.bob, body="bob's comment",
        )

    def _delete(self, user):
        self.client.force_login(user)
        return self.client.post(
            reverse("charts:delete_chart_comment", args=[self.comment.pk])
        )

    def test_author_can_delete(self):
        response = self._delete(self.bob)
        self.assertEqual(response.status_code, 302)
        self.comment.refresh_from_db()
        self.assertIsNotNone(self.comment.deleted_at)

    def test_admin_can_moderate(self):
        response = self._delete(self.admin)
        self.assertEqual(response.status_code, 302)
        self.comment.refresh_from_db()
        self.assertIsNotNone(self.comment.deleted_at)

    def test_pedagogue_can_moderate(self):
        response = self._delete(self.pedagogue)
        self.assertEqual(response.status_code, 302)
        self.comment.refresh_from_db()
        self.assertIsNotNone(self.comment.deleted_at)

    def test_stranger_cannot_delete(self):
        # alice is a regular user, not the author, not staff, not pedagogue
        response = self._delete(self.alice)
        self.assertEqual(response.status_code, 403)
        self.comment.refresh_from_db()
        self.assertIsNone(self.comment.deleted_at)


class EditCommentTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        self.song, _, _ = _make_song_chord_event()
        self.comment = ChartComment.objects.create(
            song=self.song, author=self.bob, body="original",
        )

    def test_author_can_edit(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("charts:edit_chart_comment", args=[self.comment.pk]),
            {"body": "edited"},
        )
        self.assertEqual(response.status_code, 302)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, "edited")
        self.assertIsNotNone(self.comment.edited_at)

    def test_non_author_cannot_edit(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("charts:edit_chart_comment", args=[self.comment.pk]),
            {"body": "hijacked"},
        )
        self.assertEqual(response.status_code, 403)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, "original")

    def test_deleted_comment_410(self):
        from django.utils import timezone

        self.comment.deleted_at = timezone.now()
        self.comment.save(update_fields=["deleted_at"])
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("charts:edit_chart_comment", args=[self.comment.pk]),
            {"body": "x"},
        )
        self.assertEqual(response.status_code, 410)
