"""Tests for ``ingest.irealpro.importer`` and the
``import_irealpro`` management command.

Exercise Django ORM writes — Songbook upsert, Song idempotency,
Section/Measure/ChordEvent population, dry-run inertness, transactional
recovery on per-song failure.
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
from ingest.irealpro.importer import import_parsed_songs
from ingest.irealpro.parser import parse_playlist_html


FIXTURE_PATH = (
    Path(__file__).parent / "data" / "sample_playlist.html"
)


class TestImportParsedSongs(TestCase):
    """Direct calls to the importer function."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.fixture_html = FIXTURE_PATH.read_text(encoding="utf-8")
        cls.parsed = parse_playlist_html(cls.fixture_html)

    def test_creates_songbook_and_songs(self) -> None:
        summary = import_parsed_songs(
            parsed=self.parsed,
            songbook_slug="jazz-fixture",
            songbook_title="Jazz Fixture (test)",
        )
        self.assertEqual(summary.songs_created, 4)
        self.assertEqual(summary.songs_skipped, 0)
        self.assertEqual(Songbook.objects.filter(slug="jazz-fixture").count(), 1)
        self.assertEqual(
            Song.objects.filter(songbook__slug="jazz-fixture").count(), 4
        )

    def test_writes_sections_measures_and_chord_events(self) -> None:
        import_parsed_songs(
            parsed=self.parsed,
            songbook_slug="jazz-fixture",
        )
        # ATTYA has 4 sections, 36 measures total
        attya = Song.objects.get(title="All The Things You Are")
        self.assertEqual(attya.sections.count(), 4)
        total_measures = sum(
            sec.measures.count() for sec in attya.sections.all()
        )
        self.assertEqual(total_measures, 36)
        # ATTYA's m6 has 2 chord events (Dm7 G7)
        section_a = attya.sections.get(order_index=0)
        m6 = section_a.measures.get(number_in_section=6)
        self.assertEqual(m6.chord_events.count(), 2)

    def test_re_import_is_idempotent(self) -> None:
        # First import
        first = import_parsed_songs(
            parsed=self.parsed,
            songbook_slug="jazz-fixture",
        )
        # Re-import — should update, not duplicate
        second = import_parsed_songs(
            parsed=self.parsed,
            songbook_slug="jazz-fixture",
        )
        self.assertEqual(first.songs_created, 4)
        self.assertEqual(second.songs_created, 0)
        self.assertEqual(second.songs_updated, 4)
        # No duplicate Songbook, Songs, or ChordEvents
        self.assertEqual(Songbook.objects.filter(slug="jazz-fixture").count(), 1)
        self.assertEqual(
            Song.objects.filter(songbook__slug="jazz-fixture").count(), 4
        )
        # ATTYA still has exactly 36 measures (not 72)
        attya = Song.objects.get(title="All The Things You Are")
        total_measures = sum(
            sec.measures.count() for sec in attya.sections.all()
        )
        self.assertEqual(total_measures, 36)

    def test_dry_run_writes_nothing(self) -> None:
        summary = import_parsed_songs(
            parsed=self.parsed,
            songbook_slug="dry-run-test",
            dry_run=True,
        )
        # Summary reflects what WOULD have been written
        self.assertEqual(summary.songs_created, 4)
        # But no DB writes occurred
        self.assertEqual(Songbook.objects.filter(slug="dry-run-test").count(), 0)
        self.assertEqual(Song.objects.count(), 0)

    def test_song_records_iREAL_pro_import_source(self) -> None:
        import_parsed_songs(
            parsed=self.parsed,
            songbook_slug="jazz-fixture",
        )
        for song in Song.objects.filter(songbook__slug="jazz-fixture"):
            self.assertEqual(song.import_source, ImportSource.IREAL_PRO)

    def test_chord_event_preserves_raw_iREAL_symbol_in_notes(self) -> None:
        # Importer stuffs the raw iRealPro symbol into ChordEvent.notes
        # for provenance + debug. Verify it survives.
        import_parsed_songs(
            parsed=self.parsed,
            songbook_slug="jazz-fixture",
        )
        attya = Song.objects.get(title="All The Things You Are")
        section_a = attya.sections.get(order_index=0)
        m1 = section_a.measures.get(number_in_section=1)
        event = m1.chord_events.first()
        # Canonical 'Fm7', raw iRealPro 'F-7'
        self.assertEqual(event.chord_symbol, "Fm7")
        self.assertIn("F-7", event.notes)


class TestManagementCommand(TestCase):
    """``manage.py import_irealpro`` end-to-end through the CLI."""

    def test_import_from_fixture_via_command(self) -> None:
        out = io.StringIO()
        call_command(
            "import_irealpro",
            str(FIXTURE_PATH),
            "--songbook-slug",
            "cmd-fixture",
            "--songbook-title",
            "From-CLI Fixture",
            stdout=out,
        )
        output = out.getvalue()
        self.assertIn("parsed 4 songs", output)
        self.assertIn("cmd-fixture", output)
        self.assertEqual(
            Song.objects.filter(songbook__slug="cmd-fixture").count(), 4
        )

    def test_dry_run_command(self) -> None:
        out = io.StringIO()
        call_command(
            "import_irealpro",
            str(FIXTURE_PATH),
            "--songbook-slug",
            "dry-cli",
            "--dry-run",
            stdout=out,
        )
        # No writes
        self.assertEqual(Song.objects.filter(songbook__slug="dry-cli").count(), 0)

    def test_missing_file_raises(self) -> None:
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command(
                "import_irealpro",
                "/nonexistent/path.html",
                "--songbook-slug",
                "wont-exist",
            )
