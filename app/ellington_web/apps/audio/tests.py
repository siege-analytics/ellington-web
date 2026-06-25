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


# ---------------------------------------------------------------------------
# #250 — AudioVerdict storage model
# ---------------------------------------------------------------------------


from datetime import datetime, timezone as dt_timezone  # noqa: E402

from apps.audio.models import (  # noqa: E402
    AudioVerdict, PolarityChoice, VerdictChoice,
)


class AudioVerdictModelTests(TestCase):
    def setUp(self):
        from apps.practice.models import PracticeSession, Recording
        from apps.charts.models import Song, Songbook
        from apps.styles.models import StylePreset, Master, Style, Idiom
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.user = User.objects.create_user(
            username="verdict-tester", password="pw",
        )
        sb = Songbook.objects.create(slug="verdict-sb", title="VB")
        song = Song.objects.create(
            slug="verdict-song", title="VS",
            key="C", time_signature="4/4",
            default_tempo_bpm=120, songbook=sb,
        )
        master = Master.objects.create(slug="m", name="m")
        style = Style.objects.create(slug="s", name="s")
        idiom = Idiom.objects.create(slug="i", name="i")
        preset = StylePreset.objects.create(
            slug="p", master=master, style=style, idiom=idiom,
            display_name="P",
        )
        session = PracticeSession.objects.create(
            user=self.user, song=song, target_preset=preset,
        )
        self.recording = Recording.objects.create(
            session=session, file_ref="recordings/x.wav",
        )

    def test_create_verdict_row(self):
        v = AudioVerdict.objects.create(
            recording=self.recording,
            slice_id="s-001",
            rule_id="r-001",
            rule_polarity=PolarityChoice.POSITIVE,
            verdict=VerdictChoice.SATISFIES,
            evidence_type="chord_tone_membership",
            evidence_payload={"matched": 4, "total": 4, "missing": [], "extra": []},
            verdict_confidence=0.82,
            rule_evaluability_confidence=1.0,
        )
        self.assertEqual(v.recording_id, self.recording.pk)
        self.assertEqual(v.evidence_payload["matched"], 4)

    def test_unique_constraint_on_recording_slice_rule(self):
        AudioVerdict.objects.create(
            recording=self.recording,
            slice_id="s-002", rule_id="r-002",
            rule_polarity=PolarityChoice.POSITIVE,
            verdict=VerdictChoice.NEUTRAL,
            evidence_type="deferred",
            evidence_payload={"reason": "x", "deferred_until_version": "v0.2"},
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            AudioVerdict.objects.create(
                recording=self.recording,
                slice_id="s-002", rule_id="r-002",
                rule_polarity=PolarityChoice.POSITIVE,
                verdict=VerdictChoice.VIOLATES,
                evidence_type="deferred",
                evidence_payload={},
            )

    def test_round_trip_from_dataclass(self):
        """Build a RuleVerdict dataclass + asdict() the evidence → AudioVerdict row."""
        import dataclasses
        from apps.audio.contract import (
            ChordToneMembershipEvidence, RuleVerdict,
        )

        ev = ChordToneMembershipEvidence(
            matched=3, total=4, missing=("b7",), extra=(),
        )
        rv = RuleVerdict(
            slice_id="s-003", rule_id="r-003",
            rule_polarity="positive", verdict="violates",
            evidence=ev,
            verdict_confidence=0.6,
            rule_evaluability_confidence=0.9,
        )
        row = AudioVerdict.objects.create(
            recording=self.recording,
            slice_id=rv.slice_id,
            rule_id=rv.rule_id,
            rule_polarity=rv.rule_polarity,
            verdict=rv.verdict,
            evidence_type=rv.evidence.type,
            evidence_payload=dataclasses.asdict(rv.evidence),
            verdict_confidence=rv.verdict_confidence,
            rule_evaluability_confidence=rv.rule_evaluability_confidence,
        )
        self.assertEqual(row.evidence_payload["matched"], 3)
        self.assertEqual(row.evidence_type, "chord_tone_membership")
