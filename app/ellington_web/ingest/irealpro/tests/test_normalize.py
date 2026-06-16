"""Tests for ``ingest.irealpro.normalize``.

Covers chord-symbol normalization (iRealPro vocabulary → canonical
voicings vocabulary) and per-measure chord-event splitting (one
measure-string from pyRealParser → list of timed chord events).
"""

from __future__ import annotations

from django.test import SimpleTestCase

from ingest.irealpro.normalize import (
    NormalizedChord,
    normalize_chord_symbol,
    split_measure_chord_events,
)


class TestNormalizeChordSymbol(SimpleTestCase):
    """Quality-by-quality coverage of the iRealPro → canonical map."""

    def test_major_triad(self) -> None:
        out = normalize_chord_symbol("C")
        self.assertEqual(out.canonical, "C")
        self.assertIsNone(out.bass)
        self.assertIsNone(out.warning)

    def test_minor_triad_uses_m_suffix(self) -> None:
        # iRealPro writes minor as '-'; canonical is 'm'
        self.assertEqual(normalize_chord_symbol("C-").canonical, "Cm")

    def test_minor_seven(self) -> None:
        self.assertEqual(normalize_chord_symbol("D-7").canonical, "Dm7")

    def test_minor_major_seven_with_caret(self) -> None:
        # Greene/Laukens use minor-major seven heavily; iRealPro is '-^7'
        self.assertEqual(normalize_chord_symbol("D-^7").canonical, "Dm-maj7")

    def test_major_seven_with_caret(self) -> None:
        self.assertEqual(normalize_chord_symbol("F^7").canonical, "Fmaj7")

    def test_half_diminished_h(self) -> None:
        # iRealPro uses 'h' for half-diminished; corpus uses 'm7b5'
        self.assertEqual(normalize_chord_symbol("Bh7").canonical, "Bm7b5")
        self.assertEqual(normalize_chord_symbol("F#h7").canonical, "F#m7b5")

    def test_diminished_o(self) -> None:
        self.assertEqual(normalize_chord_symbol("Bo7").canonical, "Bdim7")
        self.assertEqual(normalize_chord_symbol("Co").canonical, "Cdim")

    def test_dominant_seven(self) -> None:
        self.assertEqual(normalize_chord_symbol("G7").canonical, "G7")

    def test_dominant_with_flat_nine(self) -> None:
        # Alterations preserved verbatim — comparator uses 'C7b9' canonical
        self.assertEqual(normalize_chord_symbol("C7b9").canonical, "C7b9")

    def test_dominant_with_complex_alterations(self) -> None:
        self.assertEqual(
            normalize_chord_symbol("G7#9b13").canonical, "G7#9b13"
        )

    def test_sixth_chord(self) -> None:
        # Common in jazz (Ellington maj6, Laukens chord-melody)
        self.assertEqual(normalize_chord_symbol("C6").canonical, "C6")

    def test_six_nine_chord(self) -> None:
        self.assertEqual(normalize_chord_symbol("C69").canonical, "C6/9")

    def test_flat_root_preserved(self) -> None:
        self.assertEqual(normalize_chord_symbol("Bbmaj7").canonical[:2], "Bb")

    def test_sharp_root_preserved(self) -> None:
        self.assertEqual(normalize_chord_symbol("F#m7").canonical[:2], "F#")

    def test_slash_chord_extracts_bass(self) -> None:
        out = normalize_chord_symbol("Cmaj7/G")
        self.assertEqual(out.canonical, "Cmaj7")
        self.assertEqual(out.bass, "G")

    def test_slash_chord_with_flat_bass(self) -> None:
        out = normalize_chord_symbol("Dm7/Bb")
        self.assertEqual(out.canonical, "Dm7")
        self.assertEqual(out.bass, "Bb")

    def test_slash_chord_with_trailing_garbage_rejected(self) -> None:
        # ``Cmaj7/Gfoo`` is not a valid slash chord — the bass token must
        # be a complete root + optional accidental. fullmatch rejects;
        # the returned NormalizedChord carries a warning.
        out = normalize_chord_symbol("Cmaj7/Gfoo")
        self.assertIsNotNone(out.warning)
        self.assertIsNone(out.bass)

    def test_empty_input_yields_warning(self) -> None:
        out = normalize_chord_symbol("")
        self.assertEqual(out.canonical, "")
        self.assertIsNotNone(out.warning)

    def test_unrecognized_quality_returns_warning(self) -> None:
        # Use a token guaranteed not in the map so the warning fires.
        out = normalize_chord_symbol("Czzz")
        self.assertIsNotNone(out.warning)
        # canonical falls back to raw + rest so display still works
        self.assertIn("C", out.canonical)


class TestSplitMeasureChordEvents(SimpleTestCase):
    """One measure-string → list of (beat, raw_chord) tuples."""

    def test_single_chord_lands_on_beat_one(self) -> None:
        self.assertEqual(
            split_measure_chord_events("Fm7", 4),
            [(1.0, "Fm7")],
        )

    def test_two_chords_split_at_beat_one_and_three(self) -> None:
        # Canonical iRealPro 2-chord-bar: D-7 then G7 → beats 1 and 3
        self.assertEqual(
            split_measure_chord_events("D-7G7", 4),
            [(1.0, "D-7"), (3.0, "G7")],
        )

    def test_two_chords_with_flat_roots(self) -> None:
        self.assertEqual(
            split_measure_chord_events("Bb-7Eb7", 4),
            [(1.0, "Bb-7"), (3.0, "Eb7")],
        )

    def test_four_chords_one_per_beat(self) -> None:
        self.assertEqual(
            split_measure_chord_events("Am7D7G7C^7", 4),
            [(1.0, "Am7"), (2.0, "D7"), (3.0, "G7"), (4.0, "C^7")],
        )

    def test_sharp_in_root_stays_with_root(self) -> None:
        # C# is one chord, not two — sharp belongs to the C root
        self.assertEqual(
            split_measure_chord_events("C#m7", 4),
            [(1.0, "C#m7")],
        )

    def test_slash_bass_stays_with_chord(self) -> None:
        # F/D is one chord (F over D bass), not two
        self.assertEqual(
            split_measure_chord_events("F/D", 4),
            [(1.0, "F/D")],
        )

    def test_flat_alteration_does_not_split(self) -> None:
        # C7b9 — the 'b9' is flat-nine, not a B-root
        self.assertEqual(
            split_measure_chord_events("C7b9", 4),
            [(1.0, "C7b9")],
        )

    def test_two_single_letter_chords(self) -> None:
        # GF = G chord then F chord — must split into two
        out = split_measure_chord_events("GF", 4)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][1], "G")
        self.assertEqual(out[1][1], "F")

    def test_empty_string_yields_no_events(self) -> None:
        self.assertEqual(split_measure_chord_events("", 4), [])

    def test_three_four_time_signature_two_chords(self) -> None:
        # In 3/4: two chords go beat 1 and beat 2 (half of 3 rounded down + 1)
        out = split_measure_chord_events("D-7G7", 3)
        self.assertEqual(out[0][0], 1.0)
        self.assertEqual(out[1][0], float(3 // 2 + 1))
