"""Model-layer tests for apps.practice.

Scaffolding tests covering: slug uniqueness, FK PROTECT/CASCADE/SET_NULL
semantics, the nullability invariants, the unique-stem-per-recording-
type-model constraint, and one end-to-end chain build from
PracticeSession → Recording → AudioStem + ChordDetection → PracticeSegment.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.charts.models import Song
from apps.practice.models import (
    AudioStem,
    BackingSource,
    BackingTrack,
    ChordDetection,
    PracticeSegment,
    PracticeSession,
    Recording,
    SessionStatus,
    StemType,
)
from apps.styles.models import Critique, Style, StylePreset, StyleSelection


User = get_user_model()


def _user():
    return User.objects.create(username=f"u-{User.objects.count()}")


def _preset():
    s = Style.objects.create(slug="bebop", name="Bebop")
    return StylePreset.objects.create(slug="bebop-p", display_name="Bebop", style=s)


class BackingTrackTests(TestCase):
    def test_slug_unique(self):
        BackingTrack.objects.create(slug="biab-blues-f", title="Blues in F (BIAB)")
        with self.assertRaises(IntegrityError), transaction.atomic():
            BackingTrack.objects.create(slug="biab-blues-f", title="duplicate")

    def test_backing_track_can_have_no_style_no_song(self):
        bt = BackingTrack.objects.create(
            slug="generic-blues-f",
            title="Blues in F",
            source=BackingSource.IREAL_PRO,
        )
        self.assertIsNone(bt.style_id)
        self.assertIsNone(bt.song_id)

    def test_song_SET_NULL_on_delete(self):
        song = Song.objects.create(slug="autumn-leaves", title="Autumn Leaves")
        bt = BackingTrack.objects.create(
            slug="autumn-track", title="Autumn (BIAB)", song=song,
        )
        song.delete()
        bt.refresh_from_db()
        self.assertIsNone(bt.song_id)


class PracticeSessionTests(TestCase):
    def test_session_default_status_active(self):
        s = PracticeSession.objects.create(user=_user(), target_preset=_preset())
        self.assertEqual(s.status, SessionStatus.ACTIVE)
        self.assertIsNone(s.ended_at)

    def test_target_preset_PROTECT(self):
        preset = _preset()
        PracticeSession.objects.create(user=_user(), target_preset=preset)
        from django.db.models.deletion import ProtectedError
        with self.assertRaises(ProtectedError):
            preset.delete()

    def test_session_can_exist_without_song_or_backing(self):
        s = PracticeSession.objects.create(user=_user(), target_preset=_preset())
        self.assertIsNone(s.song_id)
        self.assertIsNone(s.backing_track_id)

    def test_recordings_cascade_on_session_delete(self):
        sess = PracticeSession.objects.create(user=_user(), target_preset=_preset())
        Recording.objects.create(session=sess, file_ref="audio:1")
        Recording.objects.create(session=sess, file_ref="audio:2")
        sess.delete()
        self.assertEqual(Recording.objects.count(), 0)


class RecordingTests(TestCase):
    def setUp(self):
        self.sess = PracticeSession.objects.create(user=_user(), target_preset=_preset())

    def test_recording_can_have_no_duration_yet(self):
        # Recording fields populated lazily as the audio finishes
        r = Recording.objects.create(session=self.sess, file_ref="audio:in-flight")
        self.assertIsNone(r.duration_ms)
        self.assertIsNone(r.sample_rate_hz)

    def test_stems_cascade_on_recording_delete(self):
        r = Recording.objects.create(session=self.sess, file_ref="audio:1")
        AudioStem.objects.create(
            recording=r, stem_type=StemType.GUITAR,
            file_ref="audio:1/guitar", separation_model_ref="demucs:v4",
        )
        AudioStem.objects.create(
            recording=r, stem_type=StemType.BASS,
            file_ref="audio:1/bass", separation_model_ref="demucs:v4",
        )
        r.delete()
        self.assertEqual(AudioStem.objects.count(), 0)


class AudioStemTests(TestCase):
    def setUp(self):
        sess = PracticeSession.objects.create(user=_user(), target_preset=_preset())
        self.rec = Recording.objects.create(session=sess, file_ref="audio:1")

    def test_unique_stem_per_recording_type_model(self):
        AudioStem.objects.create(
            recording=self.rec, stem_type=StemType.GUITAR,
            file_ref="audio:1/guitar", separation_model_ref="demucs:v4",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            AudioStem.objects.create(
                recording=self.rec, stem_type=StemType.GUITAR,
                file_ref="audio:1/guitar-duplicate", separation_model_ref="demucs:v4",
            )

    def test_same_stem_type_OK_with_different_separator(self):
        # A/B comparison of separators on the same recording — useful for sub-4
        AudioStem.objects.create(
            recording=self.rec, stem_type=StemType.GUITAR,
            file_ref="audio:1/guitar-demucs", separation_model_ref="demucs:v4",
        )
        AudioStem.objects.create(
            recording=self.rec, stem_type=StemType.GUITAR,
            file_ref="audio:1/guitar-spleeter", separation_model_ref="spleeter:5stems",
        )
        self.assertEqual(self.rec.stems.count(), 2)


class ChordDetectionTests(TestCase):
    def setUp(self):
        sess = PracticeSession.objects.create(user=_user(), target_preset=_preset())
        self.rec = Recording.objects.create(session=sess, file_ref="audio:1")

    def test_voicing_style_tags_defaults_to_empty_list(self):
        cd = ChordDetection.objects.create(
            recording=self.rec,
            beat_timestamp_ms=0,
            detected_chord_symbol="Cmaj7",
            confidence=0.95,
        )
        self.assertEqual(cd.voicing_style_tags, [])

    def test_ordered_by_timestamp(self):
        ChordDetection.objects.create(
            recording=self.rec, beat_timestamp_ms=2000,
            detected_chord_symbol="Am7", confidence=0.8,
        )
        ChordDetection.objects.create(
            recording=self.rec, beat_timestamp_ms=0,
            detected_chord_symbol="Cmaj7", confidence=0.9,
        )
        ChordDetection.objects.create(
            recording=self.rec, beat_timestamp_ms=1000,
            detected_chord_symbol="G7", confidence=0.85,
        )
        timestamps = list(self.rec.chord_detections.values_list("beat_timestamp_ms", flat=True))
        self.assertEqual(timestamps, [0, 1000, 2000])


class PracticeSegmentTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.preset = _preset()
        self.sess = PracticeSession.objects.create(user=self.user, target_preset=self.preset)
        self.rec = Recording.objects.create(session=self.sess, file_ref="audio:1")

    def test_segment_can_exist_without_critique(self):
        seg = PracticeSegment.objects.create(
            session=self.sess, recording=self.rec, start_ms=0, end_ms=5000,
        )
        self.assertIsNone(seg.critique_id)

    def test_segment_can_attach_to_critique(self):
        sel = StyleSelection.objects.create(
            user=self.user, target_preset=self.preset, backing_preset=self.preset,
        )
        crit = Critique.objects.create(
            selection=sel, style_match_score=0.8, detected_axes={},
        )
        seg = PracticeSegment.objects.create(
            session=self.sess, recording=self.rec, start_ms=0, end_ms=5000,
            critique=crit,
        )
        self.assertEqual(seg.critique, crit)
        # Critique deletion → segment.critique = NULL (segment survives)
        crit.delete()
        seg.refresh_from_db()
        self.assertIsNone(seg.critique_id)


class EndToEndChainTests(TestCase):
    """PracticeSession → Recording → AudioStem + ChordDetection →
    PracticeSegment. Mirrors the production flow once sub-4 lands.
    """

    def test_full_chain_build_and_traverse(self):
        user = _user()
        preset = _preset()
        bt = BackingTrack.objects.create(
            slug="autumn-biab", title="Autumn Leaves (BIAB)",
            source=BackingSource.BIAB, tempo_bpm=120, key="Em",
        )
        sess = PracticeSession.objects.create(
            user=user, target_preset=preset, backing_track=bt,
        )
        rec = Recording.objects.create(
            session=sess, file_ref="audio:1", duration_ms=180_000,
        )
        AudioStem.objects.create(
            recording=rec, stem_type=StemType.GUITAR,
            file_ref="audio:1/guitar", separation_model_ref="demucs:v4",
        )
        ChordDetection.objects.create(
            recording=rec, beat_timestamp_ms=0,
            detected_chord_symbol="Em7", confidence=0.95,
            voicing_style_tags=["shell", "chromatic"],
        )
        ChordDetection.objects.create(
            recording=rec, beat_timestamp_ms=4000,
            detected_chord_symbol="A7", confidence=0.92,
            voicing_style_tags=["shell"],
        )
        seg = PracticeSegment.objects.create(
            session=sess, recording=rec, start_ms=0, end_ms=8000,
            label="first chorus",
        )

        # Forward
        self.assertEqual(sess.recordings.count(), 1)
        self.assertEqual(rec.stems.count(), 1)
        self.assertEqual(rec.chord_detections.count(), 2)
        self.assertEqual(sess.segments.count(), 1)

        # Reverse
        self.assertEqual(seg.recording.session.user.pk, user.pk)
        self.assertEqual(
            list(rec.chord_detections.values_list("detected_chord_symbol", flat=True)),
            ["Em7", "A7"],
        )
