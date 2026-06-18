"""Tests for ``ingest.musescore.normalize``.

Covers the music21 ``ChordSymbol`` → canonical mapping. The structured
mapper bypasses the iRealPro string-parser entirely, so each
``chordKind`` and chord-step modification needs its own check.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from music21 import harmony as m21_harmony

from ingest.musescore.normalize import normalize_music21_chord_symbol


class TestNormalizeMusic21ChordSymbol(SimpleTestCase):
    """Quality + alteration coverage for the music21 mapper."""

    def _normalize(self, figure: str):
        return normalize_music21_chord_symbol(m21_harmony.ChordSymbol(figure))

    def test_major_triad(self) -> None:
        out = self._normalize("C")
        self.assertEqual(out.canonical, "C")
        self.assertIsNone(out.bass)
        self.assertIsNone(out.warning)

    def test_minor_seventh(self) -> None:
        self.assertEqual(self._normalize("Am7").canonical, "Am7")
        self.assertEqual(self._normalize("Dm7").canonical, "Dm7")

    def test_dominant_seventh(self) -> None:
        self.assertEqual(self._normalize("G7").canonical, "G7")

    def test_major_seventh(self) -> None:
        self.assertEqual(self._normalize("Cmaj7").canonical, "Cmaj7")

    def test_flat_root_uses_b_not_minus(self) -> None:
        # music21 spells flats with '-' (e.g. 'B-7'); canonical is 'Bb7'.
        out = self._normalize("B-7")
        self.assertEqual(out.canonical, "Bb7")

    def test_sharp_root_preserved(self) -> None:
        # F# survives as F# (no flat-to-b mangling false positive).
        out = self._normalize("F#m7")
        self.assertEqual(out.canonical, "F#m7")

    def test_diminished_seventh(self) -> None:
        self.assertEqual(self._normalize("Co7").canonical, "Cdim7")

    def test_augmented_seventh(self) -> None:
        # music21 spells it 'aug7' or 'Caug7' → canonical 7#5
        self.assertEqual(self._normalize("Caug7").canonical, "C7#5")

    def test_slash_chord_records_bass(self) -> None:
        out = self._normalize("C/G")
        self.assertEqual(out.canonical, "C")
        self.assertEqual(out.bass, "G")

    def test_root_only_no_bass(self) -> None:
        # music21 sets bass()==root() for non-slash; canonical bass=None
        out = self._normalize("C")
        self.assertIsNone(out.bass)

    def test_b9_alteration_propagates(self) -> None:
        out = self._normalize("C7b9")
        self.assertIn("b9", out.canonical)
        # Quality stays '7' so the comparator still matches on dominant.
        self.assertTrue(out.canonical.startswith("C7"))

    def test_b5_alteration_propagates(self) -> None:
        out = self._normalize("D-7b5")  # Db7b5
        self.assertEqual(out.canonical, "Db7b5")


class TestAlterationTokenSemitones(SimpleTestCase):
    """#76: ``_alteration_token`` uses ``Interval.semitones``, not name prefix.

    The prior implementation sniffed ``directedName`` (`"A1"`, `"A-1"`, `"d1"`)
    to decide flat vs sharp. Constructed ChordStepModifications with
    semitone-equivalent but unusual interval shapes (descending dim ≡ sharp,
    doubly-aug, doubly-dim) exercise the cases where prefix sniffing fails
    and semitone math succeeds.
    """

    def _make_mod(self, degree: int, interval_obj):
        from music21 import harmony as h_mod

        mod = h_mod.ChordStepModification()
        mod.degree = degree
        mod.interval = interval_obj
        return mod

    def test_ascending_aug_unison_is_sharp(self) -> None:
        from music21 import interval as i_mod

        from ingest.musescore.normalize import _alteration_token

        token = _alteration_token(self._make_mod(5, i_mod.Interval("A1")))
        self.assertEqual(token, "#5")

    def test_descending_aug_unison_is_flat(self) -> None:
        from music21 import interval as i_mod

        from ingest.musescore.normalize import _alteration_token

        token = _alteration_token(self._make_mod(9, i_mod.Interval("A-1")))
        self.assertEqual(token, "b9")

    def test_descending_dim_unison_is_sharp(self) -> None:
        # `d-1` descending dim unison = +1 semitone (same as sharp).
        # Old prefix code mis-classified this as flat; semitone math
        # gets it right.
        from music21 import interval as i_mod

        from ingest.musescore.normalize import _alteration_token

        token = _alteration_token(self._make_mod(11, i_mod.Interval("d-1")))
        self.assertEqual(token, "#11")

    def test_doubly_augmented_rejected(self) -> None:
        from music21 import interval as i_mod

        from ingest.musescore.normalize import _alteration_token

        token = _alteration_token(self._make_mod(5, i_mod.Interval("AA1")))
        self.assertIsNone(token)

    def test_perfect_unison_is_noop(self) -> None:
        from music21 import interval as i_mod

        from ingest.musescore.normalize import _alteration_token

        token = _alteration_token(self._make_mod(5, i_mod.Interval("P1")))
        self.assertEqual(token, "")
