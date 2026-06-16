"""Tests for ``ingest.irealpro.parser``.

Uses the bundled ``sample_playlist.html`` fixture (4 standards
extracted from Dheeraj's real Jazz 1400 playlist export). Round-trips
title, composer, key, time signature, section structure, and chord
progressions for songs whose harmonic content is well-known.
"""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

from ingest.irealpro.parser import (
    ParsedSong,
    parse_playlist_html,
    parse_single_uri,
)


FIXTURE_PATH = Path(__file__).parent / "data" / "sample_playlist.html"


class TestParsePlaylistHtml(SimpleTestCase):
    """Round-trip parsing of the 4-song fixture."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.html = FIXTURE_PATH.read_text(encoding="utf-8")
        cls.songs = parse_playlist_html(cls.html)
        cls.by_title: dict[str, ParsedSong] = {s.title: s for s in cls.songs}

    def test_parses_all_four_songs(self) -> None:
        self.assertEqual(len(self.songs), 4)
        self.assertEqual(
            set(self.by_title.keys()),
            {
                "All The Things You Are",
                "Autumn Leaves",
                "Bye Bye Blackbird",
                "Stella By Starlight",
            },
        )

    def test_all_the_things_you_are_metadata(self) -> None:
        s = self.by_title["All The Things You Are"]
        self.assertEqual(s.composer, "Kern Jerome")
        self.assertEqual(s.style, "Medium Up Swing")
        self.assertEqual(s.key, "Ab")
        self.assertEqual(s.time_signature, "4/4")

    def test_all_the_things_you_are_form(self) -> None:
        # AABA' = 8 + 8 + 8 + 12 = 36 bars (the canonical Kern form)
        s = self.by_title["All The Things You Are"]
        self.assertEqual(len(s.sections), 4)
        self.assertEqual(
            [len(sec.measures) for sec in s.sections],
            [8, 8, 8, 12],
        )

    def test_all_the_things_you_are_opening_changes(self) -> None:
        # First A section opens Fm7 | Bbm7 | Eb7 | Abmaj7 | Dbmaj7 | Dm7 G7 |
        # Cmaj7 | Cmaj7 — the canonical Kern progression
        s = self.by_title["All The Things You Are"]
        first_section = s.sections[0]
        opening = [m.chord_events for m in first_section.measures]

        # m1: Fm7 on beat 1
        self.assertEqual(opening[0][0].chord.canonical, "Fm7")
        # m2: Bbm7
        self.assertEqual(opening[1][0].chord.canonical, "Bbm7")
        # m3: Eb7
        self.assertEqual(opening[2][0].chord.canonical, "Eb7")
        # m4: Abmaj7
        self.assertEqual(opening[3][0].chord.canonical, "Abmaj7")
        # m6: Dm7 G7 — two chords in the bar
        self.assertEqual(len(opening[5]), 2)
        self.assertEqual(opening[5][0].chord.canonical, "Dm7")
        self.assertEqual(opening[5][1].chord.canonical, "G7")
        self.assertEqual(opening[5][0].beat, 1.0)
        self.assertEqual(opening[5][1].beat, 3.0)

    def test_autumn_leaves_key_signature(self) -> None:
        # Autumn Leaves is in G minor; iRealPro encodes minor key as 'G-'
        s = self.by_title["Autumn Leaves"]
        self.assertIn("G", s.key)

    def test_stella_by_starlight_bar_count(self) -> None:
        # Stella is 32 bars total in any of its standard forms
        s = self.by_title["Stella By Starlight"]
        total = sum(len(sec.measures) for sec in s.sections)
        self.assertEqual(total, 32)

    def test_no_unrecoverable_warnings_on_fixture(self) -> None:
        # Fixture is curated from real data — should be clean
        for s in self.songs:
            normalize_warnings = [w for w in s.warnings if "normalize" in w]
            self.assertLessEqual(
                len(normalize_warnings),
                1,
                f"{s.title}: unexpected normalize warnings: {normalize_warnings}",
            )

    def test_chord_events_carry_normalized_form(self) -> None:
        # Every ChordEvent should have a non-empty canonical chord symbol
        for s in self.songs:
            for section in s.sections:
                for measure in section.measures:
                    for event in measure.chord_events:
                        self.assertTrue(
                            event.chord.canonical,
                            f"empty canonical in {s.title}: section {section.label} "
                            f"measure {measure.number_in_section}",
                        )


class TestParseSingleUri(SimpleTestCase):
    """``parse_single_uri`` returns a list (length 1+) for any valid URI."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        html = FIXTURE_PATH.read_text(encoding="utf-8")
        import re

        match = re.search(r'irealb://([^"]+)', html)
        assert match is not None, "fixture should contain an irealb:// URI"
        cls.uri = match.group(0)

    def test_single_uri_returns_song_list(self) -> None:
        songs = parse_single_uri(self.uri)
        self.assertGreater(len(songs), 0)
        self.assertTrue(all(isinstance(s, ParsedSong) for s in songs))


class TestParsePlaylistHtmlErrors(SimpleTestCase):
    """Failure paths surface clear errors rather than crashing."""

    def test_missing_uri_raises(self) -> None:
        html = "<html><body><p>no playlist here</p></body></html>"
        with self.assertRaises(ValueError):
            parse_playlist_html(html)
