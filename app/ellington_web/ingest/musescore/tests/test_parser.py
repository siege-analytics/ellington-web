"""Tests for ``ingest.musescore.parser``.

Uses a hand-generated public-domain ``.musicxml`` fixture to exercise
the music21 → ``ParsedSong`` mapping without depending on the
``mscore`` CLI being installed in CI. The ``.mscz`` path is covered
indirectly via the CLI-discovery unit tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from ingest.musescore.parser import (
    MuseScoreNotFoundError,
    ParsedSong,
    parse_path,
)
from ingest.musescore import parser as parser_mod

FIXTURE_XML = (
    Path(__file__).parent / "data" / "two_section_sample.musicxml"
)
PASS2_XML = Path(__file__).parent / "data" / "pass2_system_breaks.musicxml"
PASS2_OVER_CAP_XML = Path(__file__).parent / "data" / "pass2_over_cap.musicxml"
# Boundary fixture: exactly _SYSTEM_BREAK_SECTION_CAP + 1 non-initial
# breaks. If the cap is ever bumped without re-running the floor logic,
# this test fails and forces re-examination.
PASS2_BOUNDARY_XML = (
    Path(__file__).parent / "data" / "pass2_boundary_cap_plus_one.musicxml"
)
PASS3_XML = Path(__file__).parent / "data" / "pass3_no_markers.musicxml"


class TestParseMusicXml(SimpleTestCase):
    """Read a MusicXML file and verify ParsedSong structure."""

    def test_returns_one_song(self) -> None:
        songs = parse_path(FIXTURE_XML)
        self.assertEqual(len(songs), 1)
        self.assertIsInstance(songs[0], ParsedSong)

    def test_metadata_lifted_from_score(self) -> None:
        song = parse_path(FIXTURE_XML)[0]
        # The fixture's composer is 'J. S. Bach (PD)'; title may be
        # synthesized ('(untitled)') depending on music21's metadata
        # parsing, so we only assert composer.
        self.assertIn("Bach", song.composer)
        self.assertEqual(song.time_signature, "4/4")

    def test_sections_detected_from_rehearsal_marks(self) -> None:
        song = parse_path(FIXTURE_XML)[0]
        labels = [s.label for s in song.sections]
        # Fixture has RehearsalMark 'A' on m1 and 'B' on m3 → two sections
        self.assertEqual(labels[:2], ["A", "B"])

    def test_chord_symbols_canonicalized(self) -> None:
        song = parse_path(FIXTURE_XML)[0]
        # Section B m1 has B-7 → must canonicalize to Bb7
        b_section = next(s for s in song.sections if s.label == "B")
        symbols = [
            ev.chord.canonical
            for m in b_section.measures
            for ev in m.chord_events
        ]
        self.assertIn("Bb7", symbols)

    def test_chord_beat_is_1_indexed(self) -> None:
        # Music21 offset 0 → beat 1; offset 2 → beat 3 in 4/4.
        song = parse_path(FIXTURE_XML)[0]
        a_section = next(s for s in song.sections if s.label == "A")
        first_measure = a_section.measures[0]
        beats = [ev.beat for ev in first_measure.chord_events]
        self.assertEqual(beats[0], 1.0)
        # Second chord on offset 2.0 in 4/4 → beat 3.0
        self.assertEqual(beats[1], 3.0)


class TestSectionFallbacks(SimpleTestCase):
    """Pass 2 (system breaks) and Pass 3 (single section) cascades."""

    def test_pass2_synthesizes_section_labels_from_system_breaks(self) -> None:
        # No RehearsalMarks, system breaks at m1 and m3 → 2 sections A / B
        song = parse_path(PASS2_XML)[0]
        labels = [s.label for s in song.sections]
        self.assertEqual(labels, ["A", "B"])
        # Warning surfaced so operators know the section labels were synthesized
        self.assertTrue(
            any("synthesized from system breaks" in w for w in song.warnings),
            f"expected synthesis warning, got {song.warnings}",
        )

    def test_pass2_over_cap_falls_through_to_single_section(self) -> None:
        # System break on every measure → would naively explode to N sections;
        # the floor (post-#74 review) demotes to Pass 3 single section.
        song = parse_path(PASS2_OVER_CAP_XML)[0]
        self.assertEqual(len(song.sections), 1)
        self.assertEqual(song.sections[0].label, "")
        # Warning explains why we abandoned Pass 2
        self.assertTrue(
            any("exceeds floor" in w for w in song.warnings),
            f"expected over-cap warning, got {song.warnings}",
        )

    def test_pass2_boundary_at_cap_plus_one_falls_through(self) -> None:
        # Fixture has exactly _SYSTEM_BREAK_SECTION_CAP + 1 non-initial
        # breaks — one more than the floor. This pins the boundary so
        # a future cap bump can't silently weaken the floor.
        from ingest.musescore import parser as parser_mod

        # Sanity check that the fixture matches the cap declared in code
        self.assertEqual(parser_mod._SYSTEM_BREAK_SECTION_CAP, 4)
        song = parse_path(PASS2_BOUNDARY_XML)[0]
        self.assertEqual(len(song.sections), 1)
        self.assertEqual(song.sections[0].label, "")
        self.assertTrue(
            any("exceeds floor" in w for w in song.warnings),
            f"expected over-cap warning, got {song.warnings}",
        )

    def test_pass3_single_unlabeled_section_when_no_markers(self) -> None:
        song = parse_path(PASS3_XML)[0]
        self.assertEqual(len(song.sections), 1)
        self.assertEqual(song.sections[0].label, "")
        self.assertTrue(
            any(
                "no RehearsalMarks or system breaks" in w
                for w in song.warnings
            ),
            f"expected pass-3 warning, got {song.warnings}",
        )


class TestMscoreCliDiscovery(SimpleTestCase):
    """``_find_mscore`` honors env-var override and falls back to PATH."""

    def test_env_var_takes_precedence(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"ELLINGTON_MSCORE_BIN": str(FIXTURE_XML)},  # any existing path
        ):
            self.assertEqual(parser_mod._find_mscore(), str(FIXTURE_XML))

    def test_env_var_nonexistent_path_returns_none(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"ELLINGTON_MSCORE_BIN": "/no/such/binary/at/all"},
            clear=False,
        ):
            # PATH may still have mscore — patch shutil.which to drop it.
            with mock.patch.object(parser_mod.shutil, "which", return_value=None):
                with mock.patch.object(
                    parser_mod.Path, "exists", return_value=False
                ):
                    self.assertIsNone(parser_mod._find_mscore())


class TestParsePathErrors(SimpleTestCase):
    """File-not-found and unsupported-extension paths return clean errors."""

    def test_missing_file_raises_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            parse_path("/no/such/file.mscz")

    def test_unsupported_extension_raises_value_error(self) -> None:
        bogus = FIXTURE_XML.with_suffix(".foo")
        bogus.write_text("not a score", encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                parse_path(bogus)
        finally:
            bogus.unlink(missing_ok=True)

    def test_key_signature_derived_via_music21_9_accessor(self) -> None:
        """#77: KeySignature.asKey().tonic.name replaces tonicPitchNameWithCase.

        Build a minimal Score in memory with a known signature and confirm
        the parser derives the expected tonic. Two fixtures: C major (0
        sharps) and F major (1 flat) — both lock the modern accessor.
        """
        from music21 import key, meter, note, stream

        from ingest.musescore.parser import _map_score

        for sharps, expected in [(0, "C"), (-1, "F")]:
            with self.subTest(sharps=sharps):
                score = stream.Score()
                part = stream.Part()
                measure = stream.Measure(number=1)
                measure.append(key.KeySignature(sharps))
                measure.append(meter.TimeSignature("4/4"))
                measure.append(note.Note("C4", quarterLength=4.0))
                part.append(measure)
                score.append(part)
                parsed = _map_score(score)
                self.assertEqual(parsed.key, expected)

    def test_mscz_without_mscore_raises_musescore_not_found(self) -> None:
        # Simulate a .mscz input when mscore is unavailable: stash the
        # fixture XML under a .mscz extension (we never actually call
        # mscore in this test path).
        fake_mscz = FIXTURE_XML.with_suffix(".mscz")
        fake_mscz.write_bytes(FIXTURE_XML.read_bytes())
        try:
            with mock.patch.object(parser_mod, "_find_mscore", return_value=None):
                with self.assertRaises(MuseScoreNotFoundError):
                    parse_path(fake_mscz)
        finally:
            fake_mscz.unlink(missing_ok=True)
