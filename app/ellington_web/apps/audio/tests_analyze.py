"""Tests for analyze_recording (#250).

The task's lazy imports mean we patch each cross-stack module
(alignment, pitch, comparator) at the import path inside the task
function. Tests do NOT exercise the real DSP — that's covered by
each module's own tests.

Skipped when the cross-stack modules aren't importable (e.g. running
on a branch that doesn't yet have the alignment / pitch / contract /
comparator PRs merged).
"""

from __future__ import annotations

import unittest
from unittest import mock

from django.test import TestCase


def _have_full_stack() -> bool:
    """Run these tests only when the full audio chain is importable."""
    try:
        from apps.audio.alignment import AlignmentResult  # noqa: F401
        from apps.audio.comparator import compare_slice  # noqa: F401
        from apps.audio.contract import RuleVerdict  # noqa: F401
        from apps.audio.pitch import PitchTrace  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(
    _have_full_stack(),
    "needs alignment + pitch + contract + comparator modules importable",
)
class AnalyzeRecordingTaskTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.audio.models import (
            BankFormat, BankSourceApp, SoundBank,
        )
        from apps.charts.models import Song, Songbook
        from apps.practice.models import (
            BackingTrack, PracticeSession, Recording,
        )
        from apps.styles.models import (
            Idiom, Master, Style, StylePreset,
        )

        UserModel = get_user_model()
        self.user = UserModel.objects.create_user(
            username="analyze-tester", password="pw",
        )
        master = Master.objects.create(slug="m", name="m")
        style = Style.objects.create(slug="s", name="s")
        idiom = Idiom.objects.create(slug="i", name="i")
        preset = StylePreset.objects.create(
            slug="p", master=master, style=style, idiom=idiom,
            display_name="P",
        )
        sb = Songbook.objects.create(slug="ab", title="AB")
        song = Song.objects.create(
            slug="analyze-song", title="AnalyzeSong",
            key="C", time_signature="4/4",
            default_tempo_bpm=120, songbook=sb,
        )
        bank = SoundBank.objects.create(
            source_app=BankSourceApp.MUSESCORE,
            name="Bank.sf3", format=BankFormat.SF3,
            path="/fake/Bank.sf3", size_bytes=1024,
            sha256="f" * 64,
        )
        backing = BackingTrack.objects.create(
            slug="bt-analyze", title="bt", song=song, bank=bank,
            audio_ref="backings/abc.wav",
            tempo_bpm=120, key="C",
        )
        self.session = PracticeSession.objects.create(
            user=self.user, song=song, target_preset=preset,
            backing_track=backing, tempo_bpm=120,
        )
        self.recording = Recording.objects.create(
            session=self.session, file_ref="recordings/test.wav",
        )

    def _patched_dependencies(self):
        """Return a context manager stack patching all cross-stack imports."""
        from apps.audio.alignment import AlignmentResult
        from apps.audio.contract import (
            ChordToneMembershipEvidence, RuleVerdict,
        )

        alignment = AlignmentResult(
            offset_seconds=0.0, confidence=0.9, tempo_drift_ratio=1.0,
        )

        class FakePitchTrace:
            def __init__(self):
                import numpy as np
                self.times = np.linspace(0, 5, 100)
                self.frequencies = np.full(100, 440.0)
                self.voicing_flag = np.ones(100, dtype=bool)
                self.sample_rate = 22050
                self.hop_length = 512

        verdict_row = RuleVerdict(
            slice_id="analyze-song-whole",
            rule_id="r-001",
            rule_polarity="positive",
            verdict="satisfies",
            evidence=ChordToneMembershipEvidence(matched=4, total=4),
            verdict_confidence=0.8,
            rule_evaluability_confidence=1.0,
        )

        return mock.patch.multiple(
            "apps.audio.analyze",
            # Block path resolution + DSP entirely; we only test the
            # orchestration glue + persistence.
        ), (alignment, FakePitchTrace(), verdict_row)

    def test_creates_audio_verdict_row_and_marks_complete(self):
        from apps.audio.alignment import AlignmentResult
        from apps.audio.contract import (
            ChordToneMembershipEvidence, RuleVerdict,
        )
        from apps.audio.models import AudioVerdict
        from apps.practice.models import AnalysisStatus

        alignment = AlignmentResult(
            offset_seconds=0.0, confidence=0.9, tempo_drift_ratio=1.0,
        )

        class FakePitchTrace:
            def __init__(self):
                import numpy as np
                self.times = np.linspace(0, 5, 100)
                self.frequencies = np.full(100, 440.0)
                self.voicing_flag = np.ones(100, dtype=bool)
                self.sample_rate = 22050
                self.hop_length = 512

        from apps.audio import analyze as analyze_module

        with mock.patch.object(
            analyze_module, "align_recording", return_value=alignment, create=True,
        ), mock.patch.object(
            analyze_module, "extract_pitch_trace", return_value=FakePitchTrace(), create=True,
        ), mock.patch.object(
            analyze_module, "fire_all", return_value=[], create=True,
        ), mock.patch.object(
            analyze_module, "compare_slice", return_value=[
                RuleVerdict(
                    slice_id="analyze-song-whole",
                    rule_id="r-001",
                    rule_polarity="positive",
                    verdict="satisfies",
                    evidence=ChordToneMembershipEvidence(matched=4, total=4),
                    verdict_confidence=0.8,
                    rule_evaluability_confidence=1.0,
                ),
            ], create=True,
        ), mock.patch(
            "apps.practice.storage.absolute_path_for", return_value="/tmp/u.wav",
        ), mock.patch(
            "apps.audio.storage.absolute_path_for", return_value="/tmp/c.wav",
        ):
            from apps.audio.analyze import analyze_recording
            count = analyze_recording(self.recording.pk)

        self.assertEqual(count, 1)
        verdict = AudioVerdict.objects.get(recording=self.recording)
        self.assertEqual(verdict.verdict, "satisfies")
        self.assertEqual(verdict.evidence_payload["matched"], 4)

        self.recording.refresh_from_db()
        self.assertEqual(
            self.recording.analysis_status, AnalysisStatus.COMPLETE,
        )

    def test_marks_failed_when_no_backing(self):
        from apps.practice.models import AnalysisStatus

        # Detach the backing
        self.session.backing_track = None
        self.session.save(update_fields=["backing_track"])

        from apps.audio.analyze import analyze_recording
        count = analyze_recording(self.recording.pk)

        self.assertEqual(count, 0)
        self.recording.refresh_from_db()
        self.assertEqual(self.recording.analysis_status, AnalysisStatus.FAILED)
