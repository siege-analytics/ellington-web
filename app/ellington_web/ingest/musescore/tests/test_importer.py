"""Tests for ``ingest.musescore.importer`` and the
``import_musescore`` management command.

Mirrors the iRealPro importer test shape — Songbook upsert, Song
idempotency, Section/Measure/ChordEvent population, dry-run inertness.
"""

from __future__ import annotations

import io
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from apps.charts.models import (
    ChordEvent,
    ImportSource,
    Measure,
    Section,
    Song,
    Songbook,
)
from ingest.musescore.importer import import_parsed_songs
from ingest.musescore.parser import parse_path

FIXTURE_XML = Path(__file__).parent / "data" / "two_section_sample.musicxml"


class TestImportParsedSongs(TestCase):
    """Direct calls to ``import_parsed_songs``."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.parsed = parse_path(FIXTURE_XML)

    def test_creates_songbook_and_song(self) -> None:
        summary = import_parsed_songs(
            parsed=self.parsed,
            songbook_slug="muse-fixture",
            songbook_title="Muse Fixture (test)",
        )
        self.assertEqual(summary.songs_created, 1)
        self.assertEqual(summary.songs_skipped, 0)
        self.assertEqual(
            Songbook.objects.filter(slug="muse-fixture").count(), 1
        )
        self.assertEqual(
            Song.objects.filter(songbook__slug="muse-fixture").count(), 1
        )

    def test_song_marked_as_musescore_source(self) -> None:
        import_parsed_songs(parsed=self.parsed, songbook_slug="muse-fixture")
        song = Song.objects.get(songbook__slug="muse-fixture")
        self.assertEqual(song.import_source, ImportSource.MUSESCORE)

    def test_writes_sections_measures_and_chord_events(self) -> None:
        import_parsed_songs(parsed=self.parsed, songbook_slug="muse-fixture")
        # Fixture has rehearsal marks A + B → at least 2 sections
        sections = Section.objects.filter(song__songbook__slug="muse-fixture")
        self.assertGreaterEqual(sections.count(), 2)
        self.assertGreater(Measure.objects.count(), 0)
        # Every measure has at least one ChordEvent except trailing
        # silence; assert at least one ChordEvent exists.
        self.assertGreater(ChordEvent.objects.count(), 0)

    def test_chord_symbols_canonical(self) -> None:
        # B-7 from MuseScore → Bb7 in the DB row
        import_parsed_songs(parsed=self.parsed, songbook_slug="muse-fixture")
        symbols = list(
            ChordEvent.objects.values_list("chord_symbol", flat=True)
        )
        self.assertIn("Bb7", symbols)

    def test_dry_run_writes_nothing(self) -> None:
        summary = import_parsed_songs(
            parsed=self.parsed,
            songbook_slug="muse-dryrun",
            dry_run=True,
        )
        self.assertEqual(summary.songs_created, 1)
        self.assertEqual(
            Songbook.objects.filter(slug="muse-dryrun").count(), 0
        )
        self.assertEqual(Song.objects.count(), 0)

    def test_reimport_is_idempotent(self) -> None:
        import_parsed_songs(parsed=self.parsed, songbook_slug="muse-fixture")
        before_songs = Song.objects.count()
        before_events = ChordEvent.objects.count()
        # Second pass: same slug → updated, not duplicated
        summary = import_parsed_songs(
            parsed=self.parsed, songbook_slug="muse-fixture"
        )
        self.assertEqual(summary.songs_updated, 1)
        self.assertEqual(summary.songs_created, 0)
        self.assertEqual(Song.objects.count(), before_songs)
        # ChordEvents should be the same count, not doubled
        self.assertEqual(ChordEvent.objects.count(), before_events)


class TestImportMuseScoreCommand(TestCase):
    """``manage.py import_musescore`` end-to-end against the XML fixture."""

    def test_command_imports_fixture(self) -> None:
        out = io.StringIO()
        call_command(
            "import_musescore",
            str(FIXTURE_XML),
            "--songbook-slug",
            "cli-fixture",
            stdout=out,
        )
        self.assertEqual(
            Song.objects.filter(songbook__slug="cli-fixture").count(), 1
        )

    def test_command_dry_run_writes_nothing(self) -> None:
        out = io.StringIO()
        call_command(
            "import_musescore",
            str(FIXTURE_XML),
            "--songbook-slug",
            "cli-dryrun",
            "--dry-run",
            stdout=out,
        )
        self.assertEqual(
            Songbook.objects.filter(slug="cli-dryrun").count(), 0
        )
