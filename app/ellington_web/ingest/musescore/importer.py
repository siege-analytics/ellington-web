"""Django ORM writer: MuseScore ``ParsedSong`` → ``apps.charts`` rows.

Idempotency contract identical to the iRealPro importer (see
:mod:`ingest.irealpro.importer`): re-importing the same file replaces a
song's sections/measures/chord-events rather than duplicating. The
``Song`` row itself is preserved via its derived slug.

The two importers don't share code yet because the iRealPro path keys
songs by ``songbook_slug + title`` and the MuseScore path keys by
``file basename + title`` (one .mscz = one song; no "songbook"
abstraction at the file level). If a third format collapses both
patterns we'll lift a shared core into ``ingest.charts_common``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils.text import slugify

from apps.charts.models import (
    ChordEvent,
    ImportSource,
    Measure,
    Section,
    Song,
    Songbook,
)

from .parser import ParsedSong

_log = logging.getLogger(__name__)


@dataclass
class ImportSummary:
    songbook_slug: str
    songs_created: int = 0
    songs_updated: int = 0
    songs_skipped: int = 0
    sections_written: int = 0
    measures_written: int = 0
    chord_events_written: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_table_rows(self) -> list[tuple[str, str]]:
        return [
            ("songbook", self.songbook_slug),
            ("songs_created", str(self.songs_created)),
            ("songs_updated", str(self.songs_updated)),
            ("songs_skipped", str(self.songs_skipped)),
            ("sections", str(self.sections_written)),
            ("measures", str(self.measures_written)),
            ("chord_events", str(self.chord_events_written)),
            ("warnings", str(len(self.warnings))),
        ]


def import_parsed_songs(
    parsed: list[ParsedSong],
    songbook_slug: str,
    songbook_title: str | None = None,
    dry_run: bool = False,
) -> ImportSummary:
    """Write MuseScore-parsed songs to the database.

    Mirrors the iRealPro importer's contract: per-song transactions
    isolate poison songs; dry_run reports what would happen without
    writing.
    """
    summary = ImportSummary(songbook_slug=songbook_slug)

    if dry_run:
        return _summarize_only(parsed, summary)

    if songbook_title is None:
        songbook, sb_created = Songbook.objects.get_or_create(
            slug=songbook_slug,
            defaults={"title": songbook_slug},
        )
    else:
        songbook, sb_created = Songbook.objects.update_or_create(
            slug=songbook_slug,
            defaults={"title": songbook_title},
        )
    _log.info(
        "songbook %s: %s",
        songbook_slug,
        "created" if sb_created else "updated",
    )

    for ps in parsed:
        try:
            with transaction.atomic():
                _import_one_song(ps, songbook, summary)
        except Exception as exc:  # noqa: BLE001 — log+skip per design
            summary.songs_skipped += 1
            summary.warnings.append(
                f"song {ps.title!r}: rolled back due to {exc!r}"
            )
            _log.warning("song %r: skipped due to %r", ps.title, exc)

    return summary


def _summarize_only(
    parsed: list[ParsedSong],
    summary: ImportSummary,
) -> ImportSummary:
    existing_slugs: set[str] = set()
    songbook = Songbook.objects.filter(slug=summary.songbook_slug).first()
    if songbook is not None:
        existing_slugs = set(
            Song.objects.filter(songbook=songbook).values_list("slug", flat=True)
        )
    for ps in parsed:
        ps_slug = _slug_for_song(ps.title, summary.songbook_slug)
        if ps_slug in existing_slugs:
            summary.songs_updated += 1
        else:
            summary.songs_created += 1
        for section in ps.sections:
            summary.sections_written += 1
            for measure in section.measures:
                summary.measures_written += 1
                summary.chord_events_written += len(measure.chord_events)
        summary.warnings.extend(
            f"song {ps.title!r}: {w}" for w in ps.warnings
        )
    return summary


def _import_one_song(
    ps: ParsedSong,
    songbook: Songbook,
    summary: ImportSummary,
) -> None:
    song_slug = _slug_for_song(ps.title, songbook.slug)
    song, created = Song.objects.update_or_create(
        slug=song_slug,
        defaults={
            "title": ps.title,
            "composer": ps.composer,
            "key": ps.key,
            "time_signature": ps.time_signature or "4/4",
            "default_tempo_bpm": ps.tempo_bpm,
            "songbook": songbook,
            "import_source": ImportSource.MUSESCORE,
        },
    )
    if created:
        summary.songs_created += 1
    else:
        summary.songs_updated += 1
        # Destructive re-import: chord-progression edits in MuseScore
        # should land verbatim, not merged, same as iRealPro path.
        song.sections.all().delete()

    summary.warnings.extend(f"song {ps.title!r}: {w}" for w in ps.warnings)

    for ps_section in ps.sections:
        section = Section.objects.create(
            song=song,
            label=ps_section.label,
            order_index=ps_section.order_index,
            measure_count=len(ps_section.measures) or None,
        )
        summary.sections_written += 1

        measures_to_create = [
            Measure(
                section=section,
                number_in_section=ps_measure.number_in_section,
            )
            for ps_measure in ps_section.measures
        ]
        Measure.objects.bulk_create(measures_to_create)
        summary.measures_written += len(measures_to_create)

        saved_measures = list(
            section.measures.order_by("number_in_section")
        )

        chord_events_to_create: list[ChordEvent] = []
        for saved_measure, ps_measure in zip(saved_measures, ps_section.measures):
            for event in ps_measure.chord_events:
                chord_events_to_create.append(
                    ChordEvent(
                        measure=saved_measure,
                        beat=Decimal(str(event.beat)),
                        chord_symbol=event.chord.canonical,
                        voicing_reference={},
                        notes=(
                            f"raw={event.chord.raw}"
                            + (
                                f"; bass={event.chord.bass}"
                                if event.chord.bass
                                else ""
                            )
                            + (
                                f"; warn={event.chord.warning}"
                                if event.chord.warning
                                else ""
                            )
                        ),
                    )
                )
        ChordEvent.objects.bulk_create(chord_events_to_create)
        summary.chord_events_written += len(chord_events_to_create)


_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slug_for_song(title: str, songbook_slug: str) -> str:
    title_slug = slugify(title)[:90]
    combined = f"{songbook_slug}--{title_slug}"
    return _SLUG_RE.sub("-", combined.lower())[:128]


__all__ = ["ImportSummary", "import_parsed_songs"]
