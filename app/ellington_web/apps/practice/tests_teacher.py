"""Tests for Teacher/Student + acknowledgement (epic #96 sub-ticket i / #126)."""

from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.charts.models import Song, Songbook
from apps.practice.models import (
    PracticeSession,
    Recording,
    RecordingComment,
    RecordingCommentAcknowledgement,
    Studio,
    StudioVisibility,
    TeacherStudent,
)
from apps.styles.models import StylePreset


User = get_user_model()


def _make_recording(owner) -> Recording:
    songbook = Songbook.objects.create(title="t")
    song = Song.objects.create(title="Song", songbook=songbook)
    preset = StylePreset.objects.create(
        slug=f"p-{secrets.token_hex(4)}", name="P",
    )
    session = PracticeSession.objects.create(
        user=owner, song=song, target_preset=preset, tempo_bpm=120,
    )
    return Recording.objects.create(session=session, file_ref="x.wav")


class TeacherStudentModelTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username="steve", password=secrets.token_urlsafe(16),
        )
        self.student = User.objects.create_user(
            username="dheeraj", password=secrets.token_urlsafe(16),
        )

    def test_basic_relationship(self):
        ts = TeacherStudent.objects.create(
            teacher=self.teacher, student=self.student,
        )
        self.assertTrue(ts.is_active)

    def test_self_teach_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeacherStudent.objects.create(
                teacher=self.teacher, student=self.teacher,
            )

    def test_active_unique_constraint(self):
        TeacherStudent.objects.create(
            teacher=self.teacher, student=self.student,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeacherStudent.objects.create(
                teacher=self.teacher, student=self.student,
            )

    def test_ended_relationship_allows_new_one(self):
        from django.utils import timezone

        old = TeacherStudent.objects.create(
            teacher=self.teacher, student=self.student,
        )
        old.ended_at = timezone.now()
        old.save()
        # Can create a fresh active relationship now
        TeacherStudent.objects.create(
            teacher=self.teacher, student=self.student,
        )
        self.assertEqual(
            TeacherStudent.objects.filter(
                teacher=self.teacher, student=self.student,
            ).count(),
            2,
        )

    def test_studio_scope(self):
        studio = Studio.objects.create(
            slug="jam", name="Jam", owner=self.teacher,
            visibility=StudioVisibility.PUBLIC,
        )
        TeacherStudent.objects.create(
            teacher=self.teacher, student=self.student, studio=studio,
        )
        # A no-studio relationship is distinct
        TeacherStudent.objects.create(
            teacher=self.teacher, student=self.student,
        )
        self.assertEqual(TeacherStudent.objects.count(), 2)


class DeclareTeacherStudentViewTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username="steve", password=secrets.token_urlsafe(16),
        )
        self.student = User.objects.create_user(
            username="dheeraj", password=secrets.token_urlsafe(16),
        )

    def test_teacher_can_declare(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("practice:declare_teacher_student"),
            {"teacher_username": "steve", "student_username": "dheeraj"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            TeacherStudent.objects.filter(
                teacher=self.teacher, student=self.student,
            ).exists()
        )

    def test_non_teacher_cannot_declare(self):
        other = User.objects.create_user(
            username="other", password=secrets.token_urlsafe(16),
        )
        self.client.force_login(other)
        response = self.client.post(
            reverse("practice:declare_teacher_student"),
            {"teacher_username": "steve", "student_username": "dheeraj"},
        )
        self.assertEqual(response.status_code, 403)


class AcknowledgementTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username="steve", password=secrets.token_urlsafe(16),
        )
        self.student = User.objects.create_user(
            username="dheeraj", password=secrets.token_urlsafe(16),
        )
        self.recording = _make_recording(self.student)
        self.comment = RecordingComment.objects.create(
            recording=self.recording, author=self.teacher,
            body="watch the voice leading at bar 5",
        )

    def test_acknowledge_creates_row(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse(
                "practice:acknowledge_recording_comment",
                args=[self.comment.pk],
            ),
            {"note": "got it, thanks"},
        )
        self.assertEqual(response.status_code, 302)
        ack = RecordingCommentAcknowledgement.objects.get()
        self.assertEqual(ack.comment, self.comment)
        self.assertEqual(ack.acknowledged_by, self.student)
        self.assertEqual(ack.note, "got it, thanks")

    def test_acknowledge_idempotent(self):
        self.client.force_login(self.student)
        for note in ("first", "second"):
            self.client.post(
                reverse(
                    "practice:acknowledge_recording_comment",
                    args=[self.comment.pk],
                ),
                {"note": note},
            )
        # update_or_create — one row, latest note
        acks = RecordingCommentAcknowledgement.objects.filter(
            comment=self.comment, acknowledged_by=self.student,
        )
        self.assertEqual(acks.count(), 1)
        self.assertEqual(acks.first().note, "second")
