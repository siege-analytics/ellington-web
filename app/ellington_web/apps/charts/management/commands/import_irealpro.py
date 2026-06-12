"""``manage.py import_irealpro`` — ingest an iRealPro playlist or single tune.

Usage::

    python manage.py import_irealpro <path-or-uri> \\
        --songbook-slug jazz-1400 \\
        [--songbook-title "Jazz 1400 playlist"] \\
        [--import-source ireal-pro] \\
        [--dry-run]

The argument is either:
    - A path to an iRealPro playlist HTML file (``.html`` from the
      "Share Playlist" export), or
    - A single ``irealb://`` URI string (single-tune format)

Idempotent: re-importing the same playlist updates existing Songs by
slug; partial-import on one bad song doesn't poison the rest.

Implements Phase 1 of ``siege-analytics/ellington-web#60``
(practice-feedback loop epic) — see ``#61`` for design.
"""

from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.charts.models import ImportSource
from ingest.irealpro.importer import import_parsed_songs
from ingest.irealpro.parser import parse_playlist_html, parse_single_uri


class Command(BaseCommand):
    help = "Import an iRealPro playlist HTML export or single-tune URI."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "source",
            help="Path to an iRealPro playlist HTML file, OR a single irealb:// URI.",
        )
        parser.add_argument(
            "--songbook-slug",
            required=True,
            help="Slug of the destination Songbook (created if absent).",
        )
        parser.add_argument(
            "--songbook-title",
            default=None,
            help="Human-readable Songbook title (defaults to the slug).",
        )
        parser.add_argument(
            "--import-source",
            default=ImportSource.IREAL_PRO,
            choices=[c[0] for c in ImportSource.choices],
            help="Value to set on Song.import_source.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse + validate but do not write to the database.",
        )

    def handle(self, *args, **options) -> None:
        source = options["source"]
        songbook_slug = options["songbook_slug"]
        songbook_title = options["songbook_title"]
        import_source = options["import_source"]
        dry_run = options["dry_run"]

        # Decide between file-path and URI. Catch broadly: OSError covers
        # permission denied, IsADirectoryError, FileNotFoundError; ValueError
        # covers parser-side bad input; UnicodeDecodeError covers non-UTF-8
        # files. All convert to a clean CommandError rather than a raw
        # traceback the operator has to dig through.
        try:
            parsed = self._parse_input(source)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            raise CommandError(str(exc)) from exc

        if not parsed:
            self.stdout.write(self.style.WARNING("no songs parsed; nothing to write"))
            return

        self.stdout.write(
            f"parsed {len(parsed)} songs from {source!r}; "
            f"writing to songbook {songbook_slug!r} (dry_run={dry_run})"
        )

        summary = import_parsed_songs(
            parsed=parsed,
            songbook_slug=songbook_slug,
            songbook_title=songbook_title,
            import_source=import_source,
            dry_run=dry_run,
        )

        # Pretty-print the summary table
        rows = summary.as_table_rows()
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            self.stdout.write(f"  {label.rjust(width)}  {value}")

        if summary.warnings:
            # Show up to first 20 warnings inline; rest go to stderr count
            self.stdout.write(self.style.WARNING(f"\n{len(summary.warnings)} warnings:"))
            for w in summary.warnings[:20]:
                self.stdout.write(f"  - {w}")
            if len(summary.warnings) > 20:
                self.stdout.write(f"  ... ({len(summary.warnings) - 20} more)")

    @staticmethod
    def _parse_input(source: str):
        """Decide between file-path and URI input, return ParsedSong list."""
        if source.startswith("irealb://"):
            return parse_single_uri(source)
        path = Path(source)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(
                f"source {source!r} is not a URI and not an existing file"
            )
        # Treat as playlist HTML
        try:
            html = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"source {source!r} is not valid UTF-8 HTML"
            ) from exc
        return parse_playlist_html(html)
