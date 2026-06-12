"""Tests for ``apps.charts.timeline`` — the chart-timeline math primitives.

Covers tempo resolution priority, time-signature parsing,
position ↔ time conversions, flattening, and the
``DetectedVoicing.measure_index`` field's coexistence with the older
``timestamp_ms`` field.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.charts.models import (
    ChordEvent,
    Measure,
    Section,
    Song,
    Songbook,
)
from apps.charts.timeline import (
    DEFAULT_TEMPO_BPM,
    beats_per_measure,
    flatten_chord_events,
    measure_to_seconds,
    resolve_tempo,
    seconds_to_measure,
    song_duration_seconds,
)


def _make_song(
    *,
    title: str = "Test Song",
    time_signature: str = "4/4",
    default_tempo_bpm: int | None = 120,
    section_specs: list[tuple[str, int]] | None = None,
) -> Song:
    """Build a Song with the given section/measure layout.

    ``section_specs`` is a list of ``(section_label, measure_count)``
    tuples. Each measure gets a single ChordEvent at beat 1.0 with
    chord_symbol equal to a placeholder (so the test can verify
    flatten_chord_events returns them in order).
    """
    if section_specs is None:
        section_specs = [("A", 4)]
    songbook = Songbook.objects.create(slug="tl-test", title="Timeline Test")
    song = Song.objects.create(
        slug=f"tl-{title.lower().replace(' ', '-')}",
        title=title,
        time_signature=time_signature,
        default_tempo_bpm=default_tempo_bpm,
        songbook=songbook,
    )
    flat = 0
    for order, (label, count) in enumerate(section_specs):
        section = Section.objects.create(
            song=song,
            label=label,
            order_index=order,
            measure_count=count,
        )
        for n in range(1, count + 1):
            flat += 1
            measure = Measure.objects.create(
                section=section,
                number_in_section=n,
            )
            ChordEvent.objects.create(
                measure=measure,
                beat=Decimal("1.0"),
                chord_symbol=f"M{flat}",
            )
    return song


class TestResolveTempo(TestCase):
    """Tempo resolution priority: arg > Song default > DEFAULT_TEMPO_BPM."""

    def test_explicit_arg_wins_over_song_default(self) -> None:
        song = _make_song(default_tempo_bpm=120)
        self.assertEqual(resolve_tempo(song, override_tempo_bpm=180), 180)

    def test_song_default_used_when_no_arg(self) -> None:
        song = _make_song(default_tempo_bpm=140)
        self.assertEqual(resolve_tempo(song), 140)

    def test_falls_back_to_default_when_song_default_is_none(self) -> None:
        song = _make_song(default_tempo_bpm=None)
        self.assertEqual(resolve_tempo(song), DEFAULT_TEMPO_BPM)

    def test_falls_back_to_default_when_song_default_is_zero(self) -> None:
        song = _make_song(default_tempo_bpm=0)
        # Model field is PositiveIntegerField so 0 should be unusual,
        # but the resolver guards against it.
        self.assertEqual(resolve_tempo(song), DEFAULT_TEMPO_BPM)


class TestBeatsPerMeasure(TestCase):
    """Time-signature numerator parsing."""

    def test_four_four(self) -> None:
        song = _make_song(time_signature="4/4")
        self.assertEqual(beats_per_measure(song), 4)

    def test_three_four(self) -> None:
        song = _make_song(time_signature="3/4")
        self.assertEqual(beats_per_measure(song), 3)

    def test_seven_eight(self) -> None:
        # Numerator parsing only — denominator is treated as
        # quarter-note for v0
        song = _make_song(time_signature="7/8")
        self.assertEqual(beats_per_measure(song), 7)

    def test_malformed_falls_back_to_four(self) -> None:
        song = _make_song(time_signature="not-a-sig")
        self.assertEqual(beats_per_measure(song), 4)


class TestMeasureToSeconds(TestCase):
    """(flat_measure_index, beat) → wall-clock seconds."""

    def test_downbeat_of_first_measure_is_zero(self) -> None:
        song = _make_song(default_tempo_bpm=120)
        self.assertEqual(measure_to_seconds(song, 1, 1.0), 0.0)

    def test_4_4_at_120_bpm_measure_2(self) -> None:
        # At 120 BPM, a 4/4 bar lasts 4 * (60/120) = 2.0 seconds
        song = _make_song(default_tempo_bpm=120, time_signature="4/4")
        self.assertEqual(measure_to_seconds(song, 2, 1.0), 2.0)

    def test_3_4_at_60_bpm_measure_2(self) -> None:
        # At 60 BPM in 3/4, a bar lasts 3 * 1.0 = 3.0 seconds
        song = _make_song(default_tempo_bpm=60, time_signature="3/4")
        self.assertEqual(measure_to_seconds(song, 2, 1.0), 3.0)

    def test_beat_fraction(self) -> None:
        # 4/4 at 120 BPM: beat 3 of measure 1 = 2 beats × 0.5 sec/beat = 1.0
        song = _make_song(default_tempo_bpm=120, time_signature="4/4")
        self.assertEqual(measure_to_seconds(song, 1, 3.0), 1.0)
        # 'and-of-2' (beat 2.5) of measure 1 = 1.5 beats × 0.5 = 0.75
        self.assertEqual(measure_to_seconds(song, 1, 2.5), 0.75)

    def test_tempo_override_changes_result(self) -> None:
        song = _make_song(default_tempo_bpm=120, time_signature="4/4")
        # Override to 240 BPM — bar takes half as long
        self.assertEqual(measure_to_seconds(song, 2, 1.0, tempo_bpm=240), 1.0)

    def test_invalid_measure_index_raises(self) -> None:
        song = _make_song()
        with self.assertRaises(ValueError):
            measure_to_seconds(song, 0, 1.0)


class TestSecondsToMeasure(TestCase):
    """seconds → (flat_measure_index, beat) — reverse of measure_to_seconds."""

    def test_zero_seconds_is_downbeat(self) -> None:
        song = _make_song()
        self.assertEqual(seconds_to_measure(song, 0.0), (1, 1.0))

    def test_round_trip_at_120_4_4(self) -> None:
        song = _make_song(default_tempo_bpm=120, time_signature="4/4")
        for m, b in [(1, 1.0), (2, 3.0), (5, 2.5), (10, 4.0)]:
            seconds = measure_to_seconds(song, m, b)
            m2, b2 = seconds_to_measure(song, seconds)
            self.assertEqual(m2, m, f"measure round-trip failed for {(m, b)}")
            self.assertAlmostEqual(b2, b, places=6)

    def test_negative_seconds_clamps_to_one_one(self) -> None:
        # Audio detectors sometimes emit slightly-negative timestamps
        # near song-start due to alignment slop — don't crash.
        song = _make_song()
        self.assertEqual(seconds_to_measure(song, -0.01), (1, 1.0))


class TestFlattenChordEvents(TestCase):
    """Walk Song → Section → Measure → ChordEvent in play order."""

    def test_single_section_four_measures(self) -> None:
        song = _make_song(section_specs=[("A", 4)])
        events = list(flatten_chord_events(song))
        self.assertEqual(len(events), 4)
        self.assertEqual([e.flat_measure_index for e in events], [1, 2, 3, 4])
        self.assertEqual(
            [e.chord_event.chord_symbol for e in events],
            ["M1", "M2", "M3", "M4"],
        )

    def test_multi_section_flat_indexing(self) -> None:
        # A=2 + B=3 + A'=2 → flat indices 1..7
        song = _make_song(section_specs=[("A", 2), ("B", 3), ("A'", 2)])
        events = list(flatten_chord_events(song))
        self.assertEqual(len(events), 7)
        self.assertEqual([e.flat_measure_index for e in events], [1, 2, 3, 4, 5, 6, 7])

    def test_section_order_respected(self) -> None:
        # Build sections out-of-order; flatten should still respect
        # order_index, not creation order.
        songbook = Songbook.objects.create(slug="order-test", title="Order")
        song = Song.objects.create(
            slug="order-song",
            title="Order Test",
            time_signature="4/4",
            default_tempo_bpm=120,
            songbook=songbook,
        )
        # Create section B first (order=1), then A (order=0)
        section_b = Section.objects.create(
            song=song, label="B", order_index=1, measure_count=1
        )
        section_a = Section.objects.create(
            song=song, label="A", order_index=0, measure_count=1
        )
        m_a = Measure.objects.create(section=section_a, number_in_section=1)
        m_b = Measure.objects.create(section=section_b, number_in_section=1)
        ChordEvent.objects.create(measure=m_a, beat=Decimal("1.0"), chord_symbol="A1")
        ChordEvent.objects.create(measure=m_b, beat=Decimal("1.0"), chord_symbol="B1")
        events = list(flatten_chord_events(song))
        # A's event should come first (flat_index=1), B's second (flat_index=2)
        self.assertEqual(events[0].chord_event.chord_symbol, "A1")
        self.assertEqual(events[1].chord_event.chord_symbol, "B1")


class TestSongDurationSeconds(TestCase):
    def test_4_bar_song_at_120_bpm_is_8_seconds(self) -> None:
        song = _make_song(
            default_tempo_bpm=120,
            time_signature="4/4",
            section_specs=[("A", 4)],
        )
        # 4 bars × 4 beats × 0.5 sec/beat = 8.0
        self.assertEqual(song_duration_seconds(song), 8.0)

    def test_empty_song_is_zero_duration(self) -> None:
        songbook = Songbook.objects.create(slug="empty", title="Empty")
        song = Song.objects.create(
            slug="empty-song",
            title="Empty",
            time_signature="4/4",
            default_tempo_bpm=120,
            songbook=songbook,
        )
        self.assertEqual(song_duration_seconds(song), 0.0)

    def test_tempo_override_respected(self) -> None:
        song = _make_song(
            default_tempo_bpm=120,
            section_specs=[("A", 4)],
        )
        # At 60 BPM (half speed), duration doubles to 16.0
        self.assertEqual(song_duration_seconds(song, tempo_bpm=60), 16.0)


class TestDetectedVoicingMeasureIndexField(TestCase):
    """The new ``measure_index`` field on DetectedVoicing — coexistence
    with ``timestamp_ms``."""

    def test_default_is_none(self) -> None:
        from apps.styles.comparator import DetectedVoicing

        dv = DetectedVoicing(chord_symbol="Cmaj7")
        self.assertIsNone(dv.measure_index)
        self.assertIsNone(dv.timestamp_ms)

    def test_can_set_measure_index_explicitly(self) -> None:
        from apps.styles.comparator import DetectedVoicing

        dv = DetectedVoicing(
            chord_symbol="Cmaj7",
            timestamp_ms=12300,
            measure_index=4,
        )
        self.assertEqual(dv.measure_index, 4)
        self.assertEqual(dv.timestamp_ms, 12300)

    def test_aligned_event_from_timeline_helpers(self) -> None:
        # Smoke: build a DetectedVoicing at timestamp 4.0s on a 120-BPM
        # 4/4 song; alignment should put it at flat_measure_index = 3.
        from apps.styles.comparator import DetectedVoicing

        song = _make_song(
            default_tempo_bpm=120,
            time_signature="4/4",
            section_specs=[("A", 8)],
        )
        timestamp_seconds = 4.0
        flat_index, beat = seconds_to_measure(song, timestamp_seconds)
        dv = DetectedVoicing(
            chord_symbol="Dm7",
            timestamp_ms=int(timestamp_seconds * 1000),
            measure_index=flat_index,
        )
        self.assertEqual(dv.measure_index, 3)
        self.assertAlmostEqual(beat, 1.0)
