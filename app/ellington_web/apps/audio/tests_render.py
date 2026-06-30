"""Tests for the MuseScore render task + storage helper (#235)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from apps.audio.models import BankFormat, BankSourceApp, SoundBank
from apps.audio.storage import absolute_path_for, store_rendered_backing
from apps.audio.tasks import RenderFailure, render_backing
from apps.charts.models import ChordEvent, Measure, Section, Song
from apps.practice.models import BackingTrack


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="ellington-audio-render-test-")


def _make_bank():
    return SoundBank.objects.create(
        source_app=BankSourceApp.MUSESCORE,
        name="TestBank.sf3",
        format=BankFormat.SF3,
        path="/fake/path/TestBank.sf3",
        size_bytes=1024,
        sha256="c" * 64,
    )


def _make_minimal_song():
    song = Song.objects.create(
        slug="minimal-song",
        title="Minimal",
        key="C",
        time_signature="4/4",
        default_tempo_bpm=120,
    )
    section = Section.objects.create(song=song, label="A", order_index=0)
    m1 = Measure.objects.create(section=section, number_in_section=1)
    ChordEvent.objects.create(
        measure=m1, beat=Decimal("1.0"), chord_symbol="Cmaj7",
    )
    return song


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class StoreRenderedBackingTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def _write_fake_wav(self, content: bytes) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="render-src-"))
        wav = tmp / "out.wav"
        wav.write_bytes(content)
        return wav

    def test_stores_under_backings_subdir(self):
        src = self._write_fake_wav(b"FAKEWAVDATA")
        result = store_rendered_backing(src)
        self.assertTrue(result.file_ref.startswith("backings/"))
        self.assertTrue(result.file_ref.endswith(".wav"))
        self.assertEqual(result.size_bytes, len(b"FAKEWAVDATA"))

    def test_idempotent_on_same_content(self):
        # First call writes; second call sees existing dest and removes src.
        src1 = self._write_fake_wav(b"IDENTICAL")
        a = store_rendered_backing(src1)
        src2 = self._write_fake_wav(b"IDENTICAL")
        b = store_rendered_backing(src2)
        self.assertEqual(a.file_ref, b.file_ref)
        self.assertEqual(a.sha256, b.sha256)
        # Only one file on disk
        files = list((Path(TEST_MEDIA_ROOT) / "backings").glob("*.wav"))
        self.assertEqual(len(files), 1)

    def test_absolute_path_for_resolves_under_media_root(self):
        src = self._write_fake_wav(b"DATA")
        result = store_rendered_backing(src)
        resolved = absolute_path_for(result.file_ref)
        self.assertTrue(resolved.is_file())
        self.assertTrue(str(resolved).startswith(TEST_MEDIA_ROOT))

    def test_absolute_path_for_blocks_traversal(self):
        with self.assertRaises(ValueError):
            absolute_path_for("../../etc/passwd")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class RenderBackingTaskTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.song = _make_minimal_song()
        self.bank = _make_bank()

    def _fake_subprocess_success(self, cmd, **kwargs):
        """Mimic mscore writing an output WAV. cmd[2] is the out path."""
        out_path = Path(cmd[2])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"FAKEWAV-" + cmd[2].encode())
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def test_creates_backing_track(self):
        with mock.patch("apps.audio.tasks.subprocess.run", side_effect=self._fake_subprocess_success):
            pk = render_backing(self.song.pk, self.bank.pk)
        bt = BackingTrack.objects.get(pk=pk)
        self.assertEqual(bt.song_id, self.song.pk)
        self.assertEqual(bt.bank_id, self.bank.pk)
        self.assertTrue(bt.audio_ref.startswith("backings/"))

    def test_idempotent_same_inputs_no_re_render(self):
        with mock.patch("apps.audio.tasks.subprocess.run", side_effect=self._fake_subprocess_success):
            pk1 = render_backing(self.song.pk, self.bank.pk)
            pk2 = render_backing(self.song.pk, self.bank.pk)
        self.assertEqual(pk1, pk2)
        # And only one BackingTrack row
        self.assertEqual(BackingTrack.objects.filter(song=self.song).count(), 1)

    def test_different_tempo_creates_new_backing(self):
        with mock.patch("apps.audio.tasks.subprocess.run", side_effect=self._fake_subprocess_success):
            pk1 = render_backing(self.song.pk, self.bank.pk, tempo_bpm=120)
            pk2 = render_backing(self.song.pk, self.bank.pk, tempo_bpm=200)
        self.assertNotEqual(pk1, pk2)
        self.assertEqual(BackingTrack.objects.filter(song=self.song).count(), 2)

    def test_nonzero_exit_raises(self):
        def _fail(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="mscore: cannot read bank")
        with mock.patch("apps.audio.tasks.subprocess.run", side_effect=_fail):
            with self.assertRaises(RenderFailure):
                render_backing(self.song.pk, self.bank.pk)

    def test_timeout_raises(self):
        def _timeout(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=300)
        with mock.patch("apps.audio.tasks.subprocess.run", side_effect=_timeout):
            with self.assertRaises(RenderFailure):
                render_backing(self.song.pk, self.bank.pk)

    def test_missing_output_raises(self):
        def _zero_but_no_output(cmd, **kwargs):
            # Returns 0 but doesn't write the output file
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        with mock.patch("apps.audio.tasks.subprocess.run", side_effect=_zero_but_no_output):
            with self.assertRaises(RenderFailure):
                render_backing(self.song.pk, self.bank.pk)
