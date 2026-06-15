"""``manage.py import_musescore`` — ingest a MuseScore ``.mscz`` / ``.musicxml`` lead sheet.

Usage::

    python manage.py import_musescore <path> \\
        --songbook-slug heads-practice \\
        [--songbook-title "Heads Practice book"] \\
        [--dry-run]

The argument is a path to a single ``.mscz``, ``.musicxml``, or
``.xml`` file. Multi-file batch import is left out of Phase 4-MS by
design — operators run this in a shell loop when ingesting a folder,
and that keeps the failure mode per-file rather than batch-wide.

Idempotent: re-importing the same file replaces an existing Song
(matched by derived slug) rather than duplicating.

Implements Phase 4-MS of ``siege-analytics/ellington-web#60`` — see
``#73`` for design.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ingest.musescore.importer import import_parsed_songs
from ingest.musescore.parser import MuseScoreNotFoundError, parse_path


class Command(BaseCommand):
    help = "Import a MuseScore .mscz / .musicxml lead sheet into apps.charts."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "source",
            help="Path to a .mscz, .musicxml, or .xml file.",
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
            "--dry-run",
            action="store_true",
            help="Parse + validate but do not write to the database.",
        )

    def handle(self, *args, **options) -> None:
        source = options["source"]
        songbook_slug = options["songbook_slug"]
        songbook_title = options["songbook_title"]
        dry_run = options["dry_run"]

        path = Path(source)
        if not path.exists() or not path.is_file():
            raise CommandError(f"source {source!r} is not an existing file")

        try:
            parsed = parse_path(path)
        except MuseScoreNotFoundError as exc:
            # mscore-CLI missing is the one infra-shaped failure that's
            # worth its own clean error: the user needs to install
            # MuseScore Studio, not debug Python.
            raise CommandError(str(exc)) from exc
        except (OSError, ValueError) as exc:
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
            dry_run=dry_run,
        )

        rows = summary.as_table_rows()
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            self.stdout.write(f"  {label.rjust(width)}  {value}")

        if summary.warnings:
            self.stdout.write(
                self.style.WARNING(f"\n{len(summary.warnings)} warnings:")
            )
            for w in summary.warnings[:20]:
                self.stdout.write(f"  - {w}")
            if len(summary.warnings) > 20:
                self.stdout.write(
                    f"  ... ({len(summary.warnings) - 20} more)"
                )
