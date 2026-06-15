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
