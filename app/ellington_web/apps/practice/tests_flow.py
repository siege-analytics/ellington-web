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

    def test_absolute_path_rejects_traversal(self) -> None:
        # ``absolute_path_for`` must refuse any file_ref that escapes
        # MEDIA_ROOT — protects future Celery workers / analyzers that
        # consume the field from a DB row they didn't construct
        # themselves.
        from apps.practice.storage import absolute_path_for

        for malicious in (
            "../etc/passwd",
            "../../etc/passwd",
            "recordings/../../etc/passwd",
            "/etc/passwd",
        ):
            with self.assertRaises(
                ValueError, msg=f"should reject: {malicious!r}"
            ):
                absolute_path_for(malicious)

    def test_absolute_path_accepts_legitimate_ref(self) -> None:
        # Files produced by store_upload must round-trip cleanly through
        # absolute_path_for after the traversal guard.
        from apps.practice.storage import absolute_path_for

        upload = _wav_upload(body=b"x")
        result = store_upload(upload, upload.name)
        resolved = absolute_path_for(result.file_ref)
        self.assertTrue(resolved.exists())


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
        # tempo_bpm lands as a proper field, not buried in Recording.notes
        self.assertEqual(session.tempo_bpm, 120)
        self.assertEqual(session.recordings.count(), 1)
        rec = session.recordings.first()
        self.assertIn("recordings/", rec.file_ref)
        # Recording.notes carries only opaque storage metadata; tempo
        # lives on the Session row now.
        self.assertNotIn("tempo_bpm", rec.notes)
        self.assertIn("sha256=", rec.notes)

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
        # tempo_bpm round-trips end-to-end (form POST → DB column)
        self.assertEqual(session.tempo_bpm, 140)
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


# ---------------------------------------------------------------------------
# #244 — bank picker + render_backing dispatch
# ---------------------------------------------------------------------------


from unittest import mock as _mock_244  # noqa: E402

from apps.audio.models import BankFormat, BankSourceApp, SoundBank  # noqa: E402


def _make_bank(name: str = "TestBank.sf3", active: bool = True) -> SoundBank:
    return SoundBank.objects.create(
        source_app=BankSourceApp.MUSESCORE,
        name=name,
        format=BankFormat.SF3,
        path=f"/fake/{name}",
        size_bytes=1024,
        sha256="d" * 64 if name == "TestBank.sf3" else "e" * 64,
        is_active=active,
    )


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class PracticeSessionFormBankPickerTests(TestCase):
    def setUp(self):
        self.user = _make_user(username="bank-tester")
        self.song = _make_song()
        self.preset = _make_preset()
        self.bank = _make_bank()

    def _form_data(self, **overrides):
        data = {
            "song": self.song.pk,
            "target_preset": self.preset.pk,
            "tempo_bpm": 140,
            "notes": "",
        }
        data.update(overrides)
        return data

    def test_bank_picker_only_lists_active(self):
        inactive = _make_bank(name="Inactive.sf3", active=False)
        form = PracticeSessionForm()
        choices = list(form.fields["bank"].queryset.values_list("pk", flat=True))
        self.assertIn(self.bank.pk, choices)
        self.assertNotIn(inactive.pk, choices)

    def test_bank_optional_form_valid_without_it(self):
        form = PracticeSessionForm(
            data=self._form_data(),
            files={"recording": _wav_upload(body=b"no-bank")},
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_save_dispatches_render_backing_when_bank_picked(self):
        form = PracticeSessionForm(
            data=self._form_data(bank=self.bank.pk),
            files={"recording": _wav_upload(body=b"with-bank")},
        )
        self.assertTrue(form.is_valid(), form.errors)
        with _mock_244.patch.object(
            form, "_dispatch_backing_render",
        ) as dispatcher:
            session = form.save(user=self.user)
        dispatcher.assert_called_once()
        kwargs = dispatcher.call_args.kwargs
        self.assertEqual(kwargs["song"].pk, self.song.pk)
        self.assertEqual(kwargs["bank"].pk, self.bank.pk)
        self.assertEqual(kwargs["tempo_bpm"], 140)
        self.assertEqual(kwargs["session"].pk, session.pk)

    def test_save_does_NOT_dispatch_when_no_bank(self):
        form = PracticeSessionForm(
            data=self._form_data(),
            files={"recording": _wav_upload(body=b"no-bank-2")},
        )
        self.assertTrue(form.is_valid(), form.errors)
        with _mock_244.patch.object(
            form, "_dispatch_backing_render",
        ) as dispatcher:
            form.save(user=self.user)
        dispatcher.assert_not_called()
# #252 — session detail renders AudioVerdict rows
# ---------------------------------------------------------------------------


class SessionDetailVerdictRenderTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = _make_user(username="verdict-render")
        from django.test import Client
        cls.client_cls = Client

    def _make_session_with_recording_and_verdict(self):
        from apps.audio.models import AudioVerdict, PolarityChoice, VerdictChoice

        song = _make_song()
        preset = _make_preset()
        session = PracticeSession.objects.create(
            user=self.user, song=song, target_preset=preset,
        )
        rec = Recording.objects.create(
            session=session, file_ref="recordings/test.wav",
        )
        AudioVerdict.objects.create(
            recording=rec,
            slice_id="s-1", rule_id="joe-pass-001",
            rule_polarity=PolarityChoice.POSITIVE,
            verdict=VerdictChoice.SATISFIES,
            evidence_type="chord_tone_membership",
            evidence_payload={
                "matched": 3, "total": 4,
                "missing": ["b7"], "extra": [],
            },
            verdict_confidence=0.82,
            rule_evaluability_confidence=1.0,
        )
        AudioVerdict.objects.create(
            recording=rec,
            slice_id="s-2", rule_id="bergonzi-vox",
            rule_polarity=PolarityChoice.POSITIVE,
            verdict=VerdictChoice.NEUTRAL,
            evidence_type="deferred",
            evidence_payload={
                "reason": "voicing-shape eval requires basic_pitch",
                "deferred_until_version": "v0.2",
            },
            verdict_confidence=0.0,
            rule_evaluability_confidence=0.0,
        )
        return session

    def test_detail_renders_verdict_block(self):
        session = self._make_session_with_recording_and_verdict()
        client = self.client_cls()
        client.force_login(self.user)
        response = client.get(reverse("practice:session_detail", args=[session.id]))
        self.assertEqual(response.status_code, 200)
        text = response.content.decode("utf-8")
        # Block header + count badge
        self.assertIn("Audio verdicts", text)
        self.assertIn("2 total", text)
        # Verdict-row content
        self.assertIn("Satisfies", text)
        self.assertIn("Neutral", text)
        self.assertIn("3 / 4 chord tones matched", text)
        self.assertIn("missing: b7", text)
        # Deferred reason rendered
        self.assertIn("voicing-shape eval requires basic_pitch", text)

    def test_detail_hides_block_when_no_verdicts(self):
        song = _make_song()
        preset = _make_preset()
        session = PracticeSession.objects.create(
            user=self.user, song=song, target_preset=preset,
        )
        Recording.objects.create(
            session=session, file_ref="recordings/no-verdicts.wav",
        )
        client = self.client_cls()
        client.force_login(self.user)
        response = client.get(reverse("practice:session_detail", args=[session.id]))
        self.assertEqual(response.status_code, 200)
        # Block header should NOT appear
        self.assertNotIn("Audio verdicts", response.content.decode("utf-8"))
