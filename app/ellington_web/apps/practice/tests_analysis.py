"""Tests for the sub-4 audio pipeline scaffolding (Phase 3a, #67).

Covers the Celery task lifecycle, the placeholder analyzer's
chart-mirroring behavior, the view-layer ``dispatch_analysis`` hook,
and the ``Recording.analysis_status`` state transitions.

Real chord detection (Phase 3b) is out of scope — these tests exercise
the *integration shape* with the chart-matching placeholder, which is
exactly what Phase 3b will swap out without changing the tested API.
"""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.charts.models import (
    ChordEvent,
    Measure,
    Section,
    Song,
    Songbook,
)
from apps.practice.analysis import analyze_recording_placeholder
from apps.practice.models import (
    AnalysisStatus,
    ChordDetection,
    PracticeSession,
    Recording,
)
from apps.practice.tasks import analyze_recording, dispatch_analysis
from apps.styles.models import StylePreset


def _build_song_with_progression(
    *,
    title: str = "Test",
    tempo: int = 120,
    time_sig: str = "4/4",
    measures_per_section: int = 2,
    sections_layout: list[str] | None = None,
) -> Song:
    """Build a Song with a tiny known progression.

    Default: 1 section ("A"), 2 measures, single chord per measure
    on beat 1. Tempo 120 BPM, 4/4. Each measure = 2 seconds.
    """
    if sections_layout is None:
        sections_layout = ["A"]
    sb = Songbook.objects.create(slug="analysis-sb", title="Analysis SB")
    song = Song.objects.create(
        slug=f"analysis-{title.lower().replace(' ', '-')}",
        title=title,
        composer="Tester",
        key="C",
        time_signature=time_sig,
        default_tempo_bpm=tempo,
        songbook=sb,
    )
    for order, label in enumerate(sections_layout):
        section = Section.objects.create(
            song=song, label=label, order_index=order, measure_count=measures_per_section
        )
        for n in range(1, measures_per_section + 1):
            m = Measure.objects.create(section=section, number_in_section=n)
            ChordEvent.objects.create(
                measure=m, beat=Decimal("1.0"), chord_symbol=f"C{order}{n}"
            )
    return song


def _build_recording(song: Song | None = None) -> Recording:
    user = get_user_model().objects.create_user("rec-user", password="pw")
    preset = StylePreset.objects.create(slug="rec-preset", display_name="Rec")
    session = PracticeSession.objects.create(
        user=user, song=song, target_preset=preset
    )
    return Recording.objects.create(session=session, file_ref="recordings/test.wav")


class TestPlaceholderAnalyzer(TestCase):
    """``analyze_recording_placeholder`` chart-mirroring behavior."""

    def test_emits_one_detection_per_chord_event(self) -> None:
        song = _build_song_with_progression()  # 1 section × 2 measures × 1 chord
        recording = _build_recording(song)
        outcome = analyze_recording_placeholder(recording)
        self.assertEqual(outcome.detections_written, 2)
        self.assertEqual(ChordDetection.objects.filter(recording=recording).count(), 2)

    def test_chord_symbols_mirror_chart(self) -> None:
        song = _build_song_with_progression()
        recording = _build_recording(song)
        analyze_recording_placeholder(recording)
        symbols = list(
            ChordDetection.objects.filter(recording=recording)
            .order_by("beat_timestamp_ms")
            .values_list("detected_chord_symbol", flat=True)
        )
        self.assertEqual(symbols, ["C01", "C02"])

    def test_timestamps_match_tempo(self) -> None:
        # 120 BPM, 4/4 → 4 beats/measure × 0.5 sec/beat = 2 sec per bar
        song = _build_song_with_progression()
        recording = _build_recording(song)
        analyze_recording_placeholder(recording)
        timestamps = sorted(
            ChordDetection.objects.filter(recording=recording).values_list(
                "beat_timestamp_ms", flat=True
            )
        )
        # m1 beat 1 = 0 ms; m2 beat 1 = 2000 ms
        self.assertEqual(timestamps, [0, 2000])

    def test_confidence_is_one(self) -> None:
        # Placeholder claims perfect confidence — Phase 3b's real detector
        # will use real (sub-1.0) confidence values.
        song = _build_song_with_progression()
        recording = _build_recording(song)
        analyze_recording_placeholder(recording)
        for det in ChordDetection.objects.filter(recording=recording):
            self.assertEqual(det.confidence, 1.0)

    def test_no_song_emits_no_detections(self) -> None:
        recording = _build_recording(song=None)
        outcome = analyze_recording_placeholder(recording)
        self.assertEqual(outcome.detections_written, 0)
        self.assertEqual(ChordDetection.objects.filter(recording=recording).count(), 0)

    def test_re_run_is_idempotent(self) -> None:
        song = _build_song_with_progression()
        recording = _build_recording(song)
        analyze_recording_placeholder(recording)
        analyze_recording_placeholder(recording)
        # Still 2 detections, not 4 — old ones wiped on re-run
        self.assertEqual(ChordDetection.objects.filter(recording=recording).count(), 2)

    def test_detection_model_ref_carries_version_tag(self) -> None:
        song = _build_song_with_progression()
        recording = _build_recording(song)
        analyze_recording_placeholder(recording)
        for det in ChordDetection.objects.filter(recording=recording):
            self.assertIn("placeholder", det.detection_model_ref)


class TestCeleryTaskLifecycle(TestCase):
    """``analyze_recording`` task: status transitions, exception handling."""

    def test_task_marks_running_then_complete(self) -> None:
        song = _build_song_with_progression()
        recording = _build_recording(song)
        # Synchronous invocation — bypass the broker
        result = analyze_recording(recording.pk)
        self.assertEqual(result["status"], "complete")
        recording.refresh_from_db()
        self.assertEqual(recording.analysis_status, AnalysisStatus.COMPLETE)
        self.assertIsNotNone(recording.analysis_completed_at)

    def test_task_with_missing_recording_returns_not_found(self) -> None:
        result = analyze_recording(999999)
        self.assertEqual(result["status"], "not-found")

    def test_task_marks_failed_on_exception(self) -> None:
        song = _build_song_with_progression()
        recording = _build_recording(song)
        with mock.patch(
            "apps.practice.tasks.analyze_recording_placeholder",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                analyze_recording(recording.pk)
        recording.refresh_from_db()
        self.assertEqual(recording.analysis_status, AnalysisStatus.FAILED)
        # Error details live in structured logs, NOT mutated into the
        # ``notes`` field — that pattern caused the concurrent-write
        # race the review caught. The status enum + log audit trail
        # are sufficient.
        self.assertNotIn("RuntimeError", recording.notes)
        self.assertNotIn("analysis_error", recording.notes)

    def test_task_does_not_mutate_notes_on_success(self) -> None:
        # Confirms the notes-append removal: completed analysis must
        # NOT touch Recording.notes. Audit lives on
        # analysis_completed_at + structured logs.
        song = _build_song_with_progression()
        recording = _build_recording(song)
        recording.notes = "user wrote this"
        recording.save()
        analyze_recording(recording.pk)
        recording.refresh_from_db()
        self.assertEqual(recording.notes, "user wrote this")


class TestDispatchAnalysis(TestCase):
    """``dispatch_analysis`` helper used by the view layer."""

    def test_sets_queued_status_and_task_id(self) -> None:
        song = _build_song_with_progression()
        recording = _build_recording(song)
        with mock.patch(
            "apps.practice.tasks.analyze_recording.delay"
        ) as mock_delay:
            mock_delay.return_value = mock.Mock(id="fake-task-id")
            task_id = dispatch_analysis(recording)
        self.assertEqual(task_id, "fake-task-id")
        recording.refresh_from_db()
        self.assertEqual(recording.analysis_status, AnalysisStatus.QUEUED)
        self.assertEqual(recording.analysis_task_id, "fake-task-id")

    def test_queued_status_set_before_delay_call(self) -> None:
        # The lifecycle race fix: status must flip to QUEUED before
        # the worker can possibly observe the row. We assert the
        # ordering by checking that the row's status was already QUEUED
        # at the moment .delay() was called.
        song = _build_song_with_progression()
        recording = _build_recording(song)

        observed_status: list[str] = []

        def fake_delay(rec_pk):
            # When the worker would pick this up, what status would
            # it see in the DB?
            observed_status.append(
                Recording.objects.get(pk=rec_pk).analysis_status
            )
            return mock.Mock(id="fake-task-id")

        with mock.patch(
            "apps.practice.tasks.analyze_recording.delay",
            side_effect=fake_delay,
        ):
            dispatch_analysis(recording)

        self.assertEqual(observed_status, [AnalysisStatus.QUEUED])

    def test_broker_failure_returns_none_and_does_not_change_status(self) -> None:
        song = _build_song_with_progression()
        recording = _build_recording(song)
        recording.analysis_status = AnalysisStatus.PENDING
        recording.save()
        with mock.patch(
            "apps.practice.tasks.analyze_recording.delay",
            side_effect=Exception("broker down"),
        ):
            task_id = dispatch_analysis(recording)
        self.assertIsNone(task_id)
        recording.refresh_from_db()
        # Stays PENDING — caller can retry
        self.assertEqual(recording.analysis_status, AnalysisStatus.PENDING)


@override_settings(MEDIA_ROOT="/tmp/ellington-test-media-67")
class TestReanalyzeView(TestCase):
    """``recording_reanalyze`` view — POST-only, login-required, owner-only."""

    def setUp(self) -> None:
        self.alice = get_user_model().objects.create_user("alice", password="pw")
        self.bob = get_user_model().objects.create_user("bob", password="pw")
        self.song = _build_song_with_progression()
        self.preset = StylePreset.objects.create(slug="re-preset", display_name="Re")
        self.alice_sess = PracticeSession.objects.create(
            user=self.alice, song=self.song, target_preset=self.preset
        )
        self.recording = Recording.objects.create(
            session=self.alice_sess, file_ref="recordings/test.wav"
        )

    def test_anonymous_redirects_to_login(self) -> None:
        url = reverse("practice:recording_reanalyze", args=[self.recording.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_other_user_gets_404(self) -> None:
        self.client.login(username="bob", password="pw")
        url = reverse("practice:recording_reanalyze", args=[self.recording.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_owner_fires_dispatch(self) -> None:
        self.client.login(username="alice", password="pw")
        with mock.patch(
            "apps.practice.views.dispatch_analysis", return_value="task-xyz"
        ) as mock_dispatch:
            response = self.client.post(
                reverse("practice:recording_reanalyze", args=[self.recording.pk])
            )
        self.assertEqual(response.status_code, 302)
        mock_dispatch.assert_called_once()
