"""Tests for apps.audio (#233 / epic #232)."""

from __future__ import annotations

import hashlib
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.audio.models import BankFormat, BankSourceApp, SoundBank


# ---------------------------------------------------------------------------
# SoundBank model
# ---------------------------------------------------------------------------


class SoundBankModelTests(TestCase):
    def test_sha256_is_unique(self):
        SoundBank.objects.create(
            source_app=BankSourceApp.MUSESCORE,
            name="MuseScore General HQ.sf3",
            format=BankFormat.SF3,
            path="/Applications/MuseScore 4.app/Contents/Resources/sound/MuseScore_General_HQ.sf3",
            size_bytes=234567,
            sha256="a" * 64,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SoundBank.objects.create(
                source_app=BankSourceApp.USER,
                name="MuseScore General HQ (duplicate path elsewhere).sf3",
                format=BankFormat.SF3,
                path="/some/other/path/HQ.sf3",
                size_bytes=234567,
                sha256="a" * 64,
            )


# ---------------------------------------------------------------------------
# scan_sound_banks command
# ---------------------------------------------------------------------------


class ScanSoundBanksCommandTests(TestCase):
    """Discovers SF2/SF3/DLS files; idempotent on sha256."""

    def setUp(self):
        # Build a fixture tree:
        #   <tmp>/musescore_install/MuseScore_General.sf3
        #   <tmp>/user_soundfonts/MyCustomBank.sf2
        #   <tmp>/some_other_garbage.txt  (excluded)
        self.root = Path(tempfile.mkdtemp(prefix="ellington-audio-test-"))
        self.musescore_dir = self.root / "musescore_install"
        self.musescore_dir.mkdir()
        self.user_dir = self.root / "user_soundfonts"
        self.user_dir.mkdir()

        self.sf3 = self.musescore_dir / "MuseScore_General.sf3"
        self.sf3.write_bytes(b"FAKE-SF3-CONTENT-A")
        self.sf2 = self.user_dir / "MyCustomBank.sf2"
        self.sf2.write_bytes(b"FAKE-SF2-CONTENT-B")
        (self.root / "noise.txt").write_text("not a bank")

    def _hash(self, b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    @mock.patch("apps.audio.management.commands.scan_sound_banks.DEFAULT_SCAN_TARGETS", [])
    def test_discovers_via_path_flag(self):
        call_command(
            "scan_sound_banks",
            "--path", str(self.musescore_dir),
            "--path", str(self.user_dir),
            stdout=StringIO(),
        )
        self.assertEqual(SoundBank.objects.count(), 2)
        sf3 = SoundBank.objects.get(format=BankFormat.SF3)
        self.assertEqual(sf3.name, "MuseScore_General.sf3")
        self.assertEqual(sf3.sha256, self._hash(b"FAKE-SF3-CONTENT-A"))
        self.assertEqual(sf3.size_bytes, len(b"FAKE-SF3-CONTENT-A"))
        # --path-tagged source is "other"
        self.assertEqual(sf3.source_app, BankSourceApp.OTHER)

    @mock.patch("apps.audio.management.commands.scan_sound_banks.DEFAULT_SCAN_TARGETS", [])
    def test_excludes_non_bank_files(self):
        call_command(
            "scan_sound_banks", "--path", str(self.root),
            stdout=StringIO(),
        )
        # Only the .sf3 + .sf2 register; noise.txt is excluded
        self.assertEqual(SoundBank.objects.count(), 2)

    @mock.patch("apps.audio.management.commands.scan_sound_banks.DEFAULT_SCAN_TARGETS", [])
    def test_idempotent_on_rerun(self):
        out1 = StringIO()
        call_command("scan_sound_banks", "--path", str(self.root), stdout=out1)
        self.assertIn("2 new", out1.getvalue())

        out2 = StringIO()
        call_command("scan_sound_banks", "--path", str(self.root), stdout=out2)
        self.assertIn("0 new", out2.getvalue())
        self.assertIn("2 already known", out2.getvalue())
        # Still only 2 rows
        self.assertEqual(SoundBank.objects.count(), 2)

    @mock.patch("apps.audio.management.commands.scan_sound_banks.DEFAULT_SCAN_TARGETS", [])
    def test_dry_run_does_not_persist(self):
        call_command(
            "scan_sound_banks", "--path", str(self.root), "--dry-run",
            stdout=StringIO(),
        )
        self.assertEqual(SoundBank.objects.count(), 0)

    @mock.patch("apps.audio.management.commands.scan_sound_banks.DEFAULT_SCAN_TARGETS", [])
    def test_env_paths_picked_up(self):
        with mock.patch.dict(
            os.environ,
            {"ELLINGTON_SOUND_BANK_PATHS": f"{self.musescore_dir}:{self.user_dir}"},
        ):
            call_command("scan_sound_banks", stdout=StringIO())
        self.assertEqual(SoundBank.objects.count(), 2)

    @mock.patch("apps.audio.management.commands.scan_sound_banks.DEFAULT_SCAN_TARGETS", [])
    def test_unreadable_path_skipped(self):
        """A configured path that doesn't exist on this machine is silently skipped."""
        call_command(
            "scan_sound_banks",
            "--path", str(self.root / "does-not-exist"),
            "--path", str(self.musescore_dir),
            stdout=StringIO(),
        )
        self.assertEqual(SoundBank.objects.count(), 1)


# ---------------------------------------------------------------------------
# BackingTrack.bank FK
# ---------------------------------------------------------------------------


class BackingTrackBankFKTests(TestCase):
    def test_backing_track_accepts_bank_fk(self):
        from apps.practice.models import BackingTrack

        bank = SoundBank.objects.create(
            source_app=BankSourceApp.MUSESCORE,
            name="MuseScore_General.sf3",
            format=BankFormat.SF3,
            path="/Applications/MuseScore 4.app/Contents/Resources/sound/MuseScore_General.sf3",
            size_bytes=10_000_000,
            sha256="b" * 64,
        )
        bt = BackingTrack.objects.create(
            slug="test-backing",
            title="test backing",
            bank=bank,
        )
        self.assertEqual(bt.bank_id, bank.pk)
        # Reverse relation
        self.assertIn(bt, bank.backing_tracks.all())
