"""Django ORM writer: ``ParsedSong[]`` → ``apps.charts`` rows.

Transactional per-song so a malformed song doesn't poison the whole
batch. Idempotent per-song: re-importing the same playlist replaces a
song's sections / measures / chord events rather than duplicating
them (the Song row itself is preserved via ``slug``).

The ``Songbook`` is upserted by ``slug``. Songs key off ``(songbook,
title)`` for the within-songbook uniqueness check, then get a stable
slug derived from ``title``.
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
    """Counts + warnings from one import run."""

    songbook_slug: str
    songs_created: int = 0
    songs_updated: int = 0
    songs_skipped: int = 0
    sections_written: int = 0
    measures_written: int = 0
    chord_events_written: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_table_rows(self) -> list[tuple[str, str]]:
        """Pretty-print rows for management-command summary output."""
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
    import_source: str = ImportSource.IREAL_PRO,
    dry_run: bool = False,
) -> ImportSummary:
    """Write parsed songs to the database.

    Returns an :class:`ImportSummary` regardless of dry_run; when
    dry_run=True, the summary's counters reflect what WOULD have been
    written but no DB writes occur.

    Per-song transactions: if one song's import raises an exception
    inside the inner transaction, that song is rolled back and counted
    as skipped, but other songs in the batch still land.
    """
    summary = ImportSummary(songbook_slug=songbook_slug)

    if dry_run:
        # Count without writing — useful for the CLI --dry-run flag
        return _summarize_only(parsed, summary)

    # Upsert songbook outside the per-song loop. If this fails, the
    # whole import fails (we can't write songs without a songbook).
    #
    # ``title`` handling: when the caller didn't specify a title, use
    # ``get_or_create`` so we don't clobber an existing custom title with
    # the slug. When the caller DID specify a title, ``update_or_create``
    # is the correct call — they explicitly want the new title applied.
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
                _import_one_song(ps, songbook, import_source, summary)
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
    """Compute what would have been written without writing.

    Distinguishes created from updated by checking which song slugs
    already exist in the target songbook. This matches the behavior
    of the real import path: a song that already exists under the same
    slug gets updated rather than created.
    """
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
    import_source: str,
    summary: ImportSummary,
) -> None:
    """Write one parsed song + its children."""
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
            "import_source": import_source,
        },
    )
    if created:
        summary.songs_created += 1
    else:
        summary.songs_updated += 1
        # Wipe existing children — re-import is destructive per design.
        # (Idempotency rationale: chord-progression edits in iRealPro
        # should land verbatim on re-import, not merged.)
        song.sections.all().delete()

    # Collect per-song warnings into the summary, prefixed by title for
    # operator readability.
    summary.warnings.extend(f"song {ps.title!r}: {w}" for w in ps.warnings)

    for ps_section in ps.sections:
        section = Section.objects.create(
            song=song,
            label=ps_section.label,
            order_index=ps_section.order_index,
            measure_count=len(ps_section.measures) or None,
        )
        summary.sections_written += 1

        # Build Measures + ChordEvents in bulk per section for speed.
        # (1400 songs × 30 measures × 1-2 chords each is ~60K writes;
        # per-row .create() would be slow.)
        measures_to_create: list[Measure] = []
        for ps_measure in ps_section.measures:
            measures_to_create.append(
                Measure(
                    section=section,
                    number_in_section=ps_measure.number_in_section,
                )
            )
        Measure.objects.bulk_create(measures_to_create)
        summary.measures_written += len(measures_to_create)

        # Need the saved Measure PKs to FK the ChordEvents — re-fetch in
        # creation order.
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
    """Derive a stable Song slug from title + songbook.

    Songbook slug is included so the same song name in different
    songbooks gets distinct slugs (a song can live in multiple
    songbooks; per model docs the FK is the canonical source).
    Trimmed to Song.slug.max_length (128).
    """
    title_slug = slugify(title)[:90]
    combined = f"{songbook_slug}--{title_slug}"
    return _SLUG_RE.sub("-", combined.lower())[:128]


__all__ = ["ImportSummary", "import_parsed_songs"]
