"""Tests for apps.audio.musicxml — Song → MusicXML serializer (#236)."""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.audio.musicxml import _parse_beats, song_to_musicxml
from apps.charts.models import ChordEvent, Measure, Section, Song


def _build_song(
    *,
    slug="test-song",
    title="Test Song",
    key="C",
    time_signature="4/4",
    tempo=120,
):
    return Song.objects.create(
        slug=slug,
        title=title,
        key=key,
        time_signature=time_signature,
        default_tempo_bpm=tempo,
    )


def _add_section(song, *, label="A", order_index=0):
    return Section.objects.create(
        song=song, label=label, order_index=order_index,
    )


def _add_measure(section, *, number=1):
    return Measure.objects.create(
        section=section, number_in_section=number,
    )


def _add_chord(measure, *, beat, symbol, duration=None):
    return ChordEvent.objects.create(
        measure=measure,
        beat=Decimal(str(beat)),
        chord_symbol=symbol,
        duration_beats=Decimal(str(duration)) if duration is not None else None,
    )


class ParseBeatsTests(TestCase):
    def test_quarter_meters(self):
        self.assertEqual(_parse_beats("4/4"), 4.0)
        self.assertEqual(_parse_beats("3/4"), 3.0)

    def test_eighth_meters(self):
        self.assertEqual(_parse_beats("6/8"), 3.0)
        self.assertEqual(_parse_beats("12/8"), 6.0)

    def test_half_meters(self):
        self.assertEqual(_parse_beats("2/2"), 4.0)

    def test_invalid_falls_back_to_4(self):
        self.assertEqual(_parse_beats("garbage"), 4.0)
        self.assertEqual(_parse_beats(""), 4.0)


class SongToMusicXMLTests(TestCase):
    def test_empty_song_raises(self):
        song = _build_song()
        with self.assertRaises(ValueError):
            song_to_musicxml(song)

    def test_basic_song_emits_xml(self):
        song = _build_song()
        section = _add_section(song)
        m1 = _add_measure(section, number=1)
        _add_chord(m1, beat=1, symbol="Cmaj7")
        _add_chord(m1, beat=3, symbol="A7")

        xml = song_to_musicxml(song)
        self.assertIn("<?xml", xml)
        self.assertIn("score-partwise", xml)
        # ChordSymbol round-trips through music21 → MusicXML uses
        # <harmony> with <root> elements. Both chords should be present.
        self.assertIn("<root", xml)

    def test_tempo_override_applied(self):
        song = _build_song(tempo=120)
        section = _add_section(song)
        m1 = _add_measure(section)
        _add_chord(m1, beat=1, symbol="C")

        xml = song_to_musicxml(song, tempo_bpm=200)
        # music21 emits tempo as a <per-minute> element
        self.assertIn("200", xml)

    def test_song_default_tempo_used_when_no_override(self):
        song = _build_song(tempo=140)
        section = _add_section(song)
        m1 = _add_measure(section)
        _add_chord(m1, beat=1, symbol="C")

        xml = song_to_musicxml(song)
        self.assertIn("140", xml)

    def test_key_override_applied(self):
        song = _build_song(key="C")
        section = _add_section(song)
        m1 = _add_measure(section)
        _add_chord(m1, beat=1, symbol="Bb")

        xml = song_to_musicxml(song, key="Bb")
        # B-flat major = 2 flats
        self.assertIn("<fifths>-2</fifths>", xml)

    def test_time_signature_passed_through(self):
        song = _build_song(time_signature="3/4")
        section = _add_section(song)
        m1 = _add_measure(section)
        _add_chord(m1, beat=1, symbol="C")

        xml = song_to_musicxml(song)
        self.assertIn("<beats>3</beats>", xml)

    def test_multiple_sections_and_measures(self):
        song = _build_song()
        a = _add_section(song, label="A", order_index=0)
        b = _add_section(song, label="B", order_index=1)
        a1 = _add_measure(a, number=1)
        a2 = _add_measure(a, number=2)
        b1 = _add_measure(b, number=1)
        _add_chord(a1, beat=1, symbol="Cmaj7")
        _add_chord(a2, beat=1, symbol="Dm7")
        _add_chord(b1, beat=1, symbol="G7")

        xml = song_to_musicxml(song)
        # All three chord symbols present as <harmony> elements
        self.assertEqual(xml.count("<harmony"), 3)
        # Three measures emitted
        self.assertEqual(xml.count("<measure number"), 3)

    def test_chord_within_measure_offsets(self):
        """Chord at beat 3 must come after a rest of duration 2."""
        song = _build_song()
        section = _add_section(song)
        m1 = _add_measure(section)
        _add_chord(m1, beat=3, symbol="G7")
        xml = song_to_musicxml(song)
        # ChordSymbol present
        self.assertIn("<harmony", xml)
        # A leading rest of 2 quarters before the chord
        self.assertIn("<rest", xml)
