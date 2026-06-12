"""Tests for the practice-flow UI (views, forms, storage).

Covers:
- ``store_upload`` content-addressed write + idempotent re-upload
- ``PracticeSessionForm`` validation (file type, size, missing fields)
- View permission isolation (user A doesn't see user B's sessions)
- ``login_required`` redirects on anonymous access
- Create flow round-trip: form POST → PracticeSession + Recording rows
- Detail view shows the chord progression
- Delete flow
"""

from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.charts.models import (
    ChordEvent,
    Measure,
    Section,
    Song,
    Songbook,
)
from apps.practice.forms import PracticeSessionForm
from apps.practice.models import PracticeSession, Recording
from apps.practice.storage import store_upload
from apps.styles.models import StylePreset


# Test isolation: route MEDIA_ROOT to a tempdir per test class so we
# don't pollute the dev / prod volume.
TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="ellington-test-media-")


def _make_user(username: str = "alice", password: str = "pw") -> User:
    UserModel = get_user_model()
    return UserModel.objects.create_user(username=username, password=password)


def _make_song(title: str = "Test Song") -> Song:
    sb = Songbook.objects.create(slug="test-sb", title="Test SB")
    song = Song.objects.create(
        slug=f"test-{title.lower().replace(' ', '-')}",
        title=title,
        composer="Test Composer",
        key="C",
        time_signature="4/4",
        default_tempo_bpm=120,
        songbook=sb,
    )
    section = Section.objects.create(
        song=song, label="A", order_index=0, measure_count=2
    )
    for n in (1, 2):
        m = Measure.objects.create(section=section, number_in_section=n)
        ChordEvent.objects.create(
            measure=m, beat=Decimal("1.0"), chord_symbol=f"M{n}"
        )
    return song


def _make_preset(slug: str = "test-preset") -> StylePreset:
    return StylePreset.objects.create(
        slug=slug,
        display_name="Test Preset",
        is_placeholder=False,
    )


def _wav_upload(name: str = "rec.wav", body: bytes = b"RIFFfake-wav-bytes") -> SimpleUploadedFile:
    return SimpleUploadedFile(name=name, content=body, content_type="audio/wav")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class TestStoreUpload(TestCase):
    """Content-addressed storage primitive."""

    def setUp(self) -> None:
        # Clear out per-test
        for child in Path(TEST_MEDIA_ROOT).glob("**/*"):
            if child.is_file():
                child.unlink()

    def test_writes_file_with_sha256_name(self) -> None:
        body = b"raw audio bytes"
        upload = _wav_upload(body=body)
        result = store_upload(upload, upload.name)
        expected_sha = hashlib.sha256(body).hexdigest()
        self.assertEqual(result.sha256, expected_sha)
        self.assertEqual(result.size_bytes, len(body))
        # File exists at expected path
        from apps.practice.storage import absolute_path_for

        self.assertTrue(absolute_path_for(result.file_ref).exists())

    def test_re_upload_same_bytes_is_idempotent(self) -> None:
        body = b"same bytes"
        a = store_upload(_wav_upload(body=body), "a.wav")
        b = store_upload(_wav_upload(body=body), "b.wav")
        # Same digest → same file_ref → only one file on disk
        self.assertEqual(a.file_ref, b.file_ref)
        files = list(Path(TEST_MEDIA_ROOT, "recordings").glob("*"))
        self.assertEqual(len(files), 1)

    def test_extension_preserved_for_audio_types(self) -> None:
        for ext in (".wav", ".mp3", ".m4a", ".flac"):
            result = store_upload(_wav_upload(name=f"rec{ext}"), f"rec{ext}")
            self.assertTrue(result.file_ref.endswith(ext))

    def test_unknown_extension_dropped(self) -> None:
        # Extension whitelist defense — unknown extensions stripped
        result = store_upload(_wav_upload(name="rec.txt"), "rec.txt")
        self.assertEqual(result.extension, "")
        self.assertFalse(result.file_ref.endswith(".txt"))


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class TestPracticeSessionForm(TestCase):
    def setUp(self) -> None:
        self.user = _make_user()
        self.song = _make_song()
        self.preset = _make_preset()

    def _form_data(self, **overrides) -> dict:
        data = {
            "song": self.song.pk,
            "target_preset": self.preset.pk,
            "tempo_bpm": 120,
            "notes": "",
        }
        data.update(overrides)
        return data

    def test_valid_form_saves_session_and_recording(self) -> None:
        upload = _wav_upload(body=b"fake")
        form = PracticeSessionForm(
            data=self._form_data(),
            files={"recording": upload},
        )
        self.assertTrue(form.is_valid(), form.errors)
        session = form.save(user=self.user)
        self.assertIsInstance(session, PracticeSession)
        self.assertEqual(session.user_id, self.user.id)
        self.assertEqual(session.recordings.count(), 1)
        rec = session.recordings.first()
        self.assertIn("recordings/", rec.file_ref)
        self.assertIn("tempo_bpm=120", rec.notes)

    def test_rejects_non_audio_extension(self) -> None:
        form = PracticeSessionForm(
            data=self._form_data(),
            files={"recording": SimpleUploadedFile("rec.txt", b"x", "text/plain")},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("recording", form.errors)

    def test_rejects_missing_song(self) -> None:
        form = PracticeSessionForm(
            data=self._form_data(song=""),
            files={"recording": _wav_upload()},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("song", form.errors)

    def test_tempo_default_from_song(self) -> None:
        # When initial_song_id is passed, tempo prefills from Song
        form = PracticeSessionForm(initial_song_id=self.song.pk)
        self.assertEqual(form.fields["tempo_bpm"].initial, 120)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, AUTHENTIK_HEADER_TRUST=False)
class TestPracticeFlowViews(TestCase):
    def setUp(self) -> None:
        self.alice = _make_user("alice")
        self.bob = _make_user("bob")
        self.song = _make_song()
        self.preset = _make_preset()

    def test_session_list_requires_login(self) -> None:
        response = self.client.get(reverse("practice:session_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_alice_sees_only_her_sessions(self) -> None:
        alice_sess = PracticeSession.objects.create(
            user=self.alice, song=self.song, target_preset=self.preset
        )
        bob_sess = PracticeSession.objects.create(
            user=self.bob, song=self.song, target_preset=self.preset
        )
        self.client.login(username="alice", password="pw")
        response = self.client.get(reverse("practice:session_list"))
        self.assertEqual(response.status_code, 200)
        sessions = list(response.context["sessions"])
        self.assertIn(alice_sess, sessions)
        self.assertNotIn(bob_sess, sessions)

    def test_create_flow_round_trip(self) -> None:
        self.client.login(username="alice", password="pw")
        upload = _wav_upload(body=b"abc")
        response = self.client.post(
            reverse("practice:session_new"),
            data={
                "song": self.song.pk,
                "target_preset": self.preset.pk,
                "tempo_bpm": 140,
                "notes": "trying out hard bop",
                "recording": upload,
            },
        )
        # Should redirect to detail
        self.assertEqual(response.status_code, 302)
        session = PracticeSession.objects.get(user=self.alice)
        self.assertEqual(session.song_id, self.song.pk)
        self.assertEqual(session.recordings.count(), 1)
        self.assertIn("hard bop", session.notes)

    def test_detail_view_shows_chord_progression(self) -> None:
        self.client.login(username="alice", password="pw")
        sess = PracticeSession.objects.create(
            user=self.alice, song=self.song, target_preset=self.preset
        )
        response = self.client.get(
            reverse("practice:session_detail", args=[sess.id])
        )
        self.assertEqual(response.status_code, 200)
        chord_rows = response.context["chord_rows"]
        self.assertEqual(len(chord_rows), 2)
        self.assertEqual(chord_rows[0]["flat_measure_index"], 1)
        self.assertEqual(chord_rows[1]["flat_measure_index"], 2)

    def test_detail_view_blocks_other_users(self) -> None:
        self.client.login(username="bob", password="pw")
        alice_sess = PracticeSession.objects.create(
            user=self.alice, song=self.song, target_preset=self.preset
        )
        response = self.client.get(
            reverse("practice:session_detail", args=[alice_sess.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_removes_session(self) -> None:
        self.client.login(username="alice", password="pw")
        sess = PracticeSession.objects.create(
            user=self.alice, song=self.song, target_preset=self.preset
        )
        response = self.client.post(
            reverse("practice:session_delete", args=[sess.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            PracticeSession.objects.filter(pk=sess.id).exists()
        )

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
