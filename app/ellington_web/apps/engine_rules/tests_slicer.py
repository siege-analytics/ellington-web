"""Tests for apps.engine_rules.slicer (#180).

Slice production from a Song. Verifies linear traversal in form order,
prev/next propagation across section boundaries, augmentation, and the
empty/missing edge cases.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.charts.models import (
    ChordEvent,
    Measure,
    Section,
    Song,
)
from apps.engine_rules.slicer import slices_for_song


def _make_song(slug: str = "test-song", **kwargs) -> Song:
    defaults = dict(
        slug=slug,
        title="Test Song",
        key="C",
        time_signature="4/4",
    )
    defaults.update(kwargs)
    return Song.objects.create(**defaults)


def _add_chords(section: Section, *, measure_number: int, chords_at_beats: list[tuple[float, str]]):
    """Helper — create one Measure with the given beat→chord events."""
    measure = Measure.objects.create(section=section, number_in_section=measure_number)
    for beat, symbol in chords_at_beats:
        ChordEvent.objects.create(
            measure=measure, beat=Decimal(str(beat)), chord_symbol=symbol,
        )
    return measure


class SlicerSingleSectionTests(TestCase):

    def setUp(self):
        self.song = _make_song()
        self.A = Section.objects.create(song=self.song, label="A", order_index=0)
        _add_chords(self.A, measure_number=1, chords_at_beats=[
            (1.0, "Cmaj7"),
            (3.0, "G7"),
        ])
        _add_chords(self.A, measure_number=2, chords_at_beats=[
            (1.0, "Dm7"),
            (3.0, "G7"),
        ])

    def test_emits_one_slice_per_chord_event(self):
        slices = list(slices_for_song(self.song))
        self.assertEqual(len(slices), 4)
        chord_stream = [s.target_chord_canonical for s in slices]
        self.assertEqual(chord_stream, ["Cmaj7", "G7", "Dm7", "G7"])

    def test_prev_next_at_boundaries(self):
        slices = list(slices_for_song(self.song))
        # first slice has no prev
        self.assertIsNone(slices[0].prev_chord_canonical)
        self.assertEqual(slices[0].next_chord_canonical, "G7")
        # middle slice
        self.assertEqual(slices[1].prev_chord_canonical, "Cmaj7")
        self.assertEqual(slices[1].next_chord_canonical, "Dm7")
        # last slice has no next
        self.assertEqual(slices[-1].prev_chord_canonical, "Dm7")
        self.assertIsNone(slices[-1].next_chord_canonical)

    def test_slice_dimensions_populated_from_song(self):
        slices = list(slices_for_song(self.song))
        first = slices[0]
        self.assertEqual(first.key, "C")
        self.assertEqual(first.section_label, "A")
        self.assertEqual(first.beat_in_measure, 1.0)
        self.assertEqual(first.time_signature, "4/4")

    def test_augmentation_populated(self):
        slices = list(slices_for_song(self.song))
        # Cmaj7 augments to maj7
        self.assertEqual(slices[0].chord_quality, "maj7")
        self.assertEqual(slices[0].chord_family, "maj")
        # G7 augments to dom7
        self.assertEqual(slices[1].chord_quality, "dom7")
        self.assertEqual(slices[1].chord_family, "dom7")


class SlicerMultiSectionTests(TestCase):

    def test_prev_next_propagates_across_section_boundary(self):
        song = _make_song(slug="aaba-form")
        A = Section.objects.create(song=song, label="A", order_index=0)
        B = Section.objects.create(song=song, label="B", order_index=1)
        _add_chords(A, measure_number=1, chords_at_beats=[(1.0, "Cmaj7")])
        _add_chords(B, measure_number=1, chords_at_beats=[(1.0, "Em7"), (3.0, "A7")])

        slices = list(slices_for_song(song))
        chord_stream = [s.target_chord_canonical for s in slices]
        section_stream = [s.section_label for s in slices]
        self.assertEqual(chord_stream, ["Cmaj7", "Em7", "A7"])
        self.assertEqual(section_stream, ["A", "B", "B"])

        # The B-section's first slice should see Cmaj7 as its prev_chord
        # (crossing the section boundary).
        self.assertEqual(slices[1].prev_chord_canonical, "Cmaj7")
        self.assertEqual(slices[1].section_label, "B")


class SlicerEdgeCasesTests(TestCase):

    def test_empty_song_yields_no_slices(self):
        song = _make_song(slug="empty-song")
        self.assertEqual(list(slices_for_song(song)), [])

    def test_section_with_measures_but_no_chord_events(self):
        song = _make_song(slug="chordless")
        section = Section.objects.create(song=song, label="A", order_index=0)
        Measure.objects.create(section=section, number_in_section=1)
        self.assertEqual(list(slices_for_song(song)), [])

    def test_empty_chord_symbol_rows_skipped(self):
        song = _make_song(slug="with-blanks")
        section = Section.objects.create(song=song, label="A", order_index=0)
        measure = Measure.objects.create(section=section, number_in_section=1)
        ChordEvent.objects.create(measure=measure, beat=Decimal("1.0"), chord_symbol="Cmaj7")
        ChordEvent.objects.create(measure=measure, beat=Decimal("2.0"), chord_symbol="")
        ChordEvent.objects.create(measure=measure, beat=Decimal("3.0"), chord_symbol="G7")
        slices = list(slices_for_song(song))
        self.assertEqual([s.target_chord_canonical for s in slices], ["Cmaj7", "G7"])
        # prev/next correctly skips the blank
        self.assertEqual(slices[1].prev_chord_canonical, "Cmaj7")

    def test_time_signature_override_takes_precedence(self):
        song = _make_song(slug="meter-change", time_signature="4/4")
        section = Section.objects.create(song=song, label="A", order_index=0)
        weird_measure = Measure.objects.create(
            section=section, number_in_section=1, time_signature_override="3/4",
        )
        ChordEvent.objects.create(
            measure=weird_measure, beat=Decimal("1.0"), chord_symbol="Cmaj7",
        )
        slices = list(slices_for_song(song))
        self.assertEqual(slices[0].time_signature, "3/4")

    def test_song_without_key_emits_none(self):
        song = _make_song(slug="keyless", key="")
        section = Section.objects.create(song=song, label="A", order_index=0)
        measure = Measure.objects.create(section=section, number_in_section=1)
        ChordEvent.objects.create(measure=measure, beat=Decimal("1.0"), chord_symbol="Cmaj7")
        slices = list(slices_for_song(song))
        self.assertIsNone(slices[0].key)


class SlicerIntegrationWithFiringTests(TestCase):
    """End-to-end: produce slices from a chart, fire rules against them."""

    def test_song_slices_fed_to_fire_all_produce_expected_matches(self):
        from apps.engine_rules.firing import fire_all

        # ii-V-I in C
        song = _make_song(slug="ii-v-i")
        A = Section.objects.create(song=song, label="A", order_index=0)
        _add_chords(A, measure_number=1, chords_at_beats=[
            (1.0, "Dm7"),
            (3.0, "G7"),
        ])
        _add_chords(A, measure_number=2, chords_at_beats=[
            (1.0, "Cmaj7"),
        ])

        rules = [
            {  # fires on dom7 quality — should hit the G7 slice only
                "rule_id": "dom7-only",
                "quality_binding": ["dom7"],
                "when": {},
                "preference": 1,
            },
            {  # fires on min7 — hits Dm7
                "rule_id": "min7-only",
                "quality_binding": ["min7"],
                "when": {},
                "preference": 0,
            },
            {  # fires on maj7 — hits Cmaj7
                "rule_id": "maj7-only",
                "quality_binding": ["maj7"],
                "when": {},
                "preference": 2,
            },
        ]

        slices = list(slices_for_song(song))
        per_slice_fires = {
            s.target_chord_canonical: [r.rule_id for r in fire_all(rules, s)]
            for s in slices
        }
        self.assertEqual(per_slice_fires, {
            "Dm7": ["min7-only"],
            "G7": ["dom7-only"],
            "Cmaj7": ["maj7-only"],
        })
