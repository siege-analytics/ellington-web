"""iRealPro playlist parser — HTML or URI → ``ParsedSong`` dataclasses.

Wraps :mod:`pyRealParser` for the deobfuscation + structural parsing
(which is the hard, format-specific work nobody should re-derive), then
maps the result into our own dataclasses so the importer can write
``apps.charts`` rows without knowing about iRealPro's quirks.

pyRealParser quirks we work around here:

- It calls ``parse_ireal_url`` rather than ``parse_ireal_html``; we
  extract the ``irealb://`` URI from the playlist HTML ourselves and
  pass that in.
- The playlist's last "tune" is actually the playlist name (e.g.
  ``Jazz 1400``), not a real song. We detect and skip these.
- ``measures_as_strings`` already expands repeats and ``x``
  (repeat-previous-measure) markers — good, we want the played
  sequence as the timeline.
- Section labels live in the raw ``chord_string`` as ``*A``, ``*B``
  etc. markers between ``[`` ``]`` brackets; we re-walk that to
  recover Section structure for our model.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .normalize import (
    NormalizedChord,
    normalize_chord_symbol,
    split_measure_chord_events,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Frozen typed shape: importer + tests + management command consume these
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedChordEvent:
    """One chord at a specific beat within a measure (1-indexed beat)."""

    beat: float
    chord: NormalizedChord


@dataclass(frozen=True)
class ParsedMeasure:
    """One bar — 1-indexed within its section."""

    number_in_section: int
    chord_events: tuple[ParsedChordEvent, ...]


@dataclass(frozen=True)
class ParsedSection:
    """A formal section (A, B, Bridge, etc.) of a song."""

    label: str
    order_index: int  # 0-based, per Section model
    measures: tuple[ParsedMeasure, ...]


@dataclass(frozen=True)
class ParsedSong:
    """One iRealPro tune mapped to our dataclasses.

    ``warnings`` collects any non-fatal issues from parsing /
    normalization (unrecognized chord symbols, structural quirks). The
    importer surfaces them to the import log. Empty tuple = clean parse.
    """

    title: str
    composer: str
    style: str
    key: str
    time_signature: str  # "4/4", "3/4", etc. — canonical form for Song.time_signature
    tempo_bpm: int | None
    sections: tuple[ParsedSection, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_playlist_html(html: str) -> list[ParsedSong]:
    """Parse an iRealPro playlist HTML export into ``ParsedSong[]``.

    The HTML wraps one (or rarely more) ``irealb://`` URI in an ``<a
    href=...>`` tag. We extract the URI and delegate to pyRealParser
    for deobfuscation, then map the result.

    Songs whose chord_string is empty (e.g. the playlist-name marker
    pyRealParser tries to parse as a final "tune") are skipped without
    warning — that's expected playlist structure, not a parse failure.
    """
    uri = _extract_irealb_uri(html)
    if uri is None:
        raise ValueError("no irealb:// URI found in playlist HTML")
    return _parse_uri(uri)


def parse_single_uri(uri: str) -> list[ParsedSong]:
    """Parse a single ``irealb://`` URI — same return shape as the playlist parser.

    A single-tune URI just has one song; this returns a list of length 1
    on success. Same dataclass shape so callers can treat both inputs
    uniformly.
    """
    return _parse_uri(uri)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


_IREALB_URI_RE = re.compile(r'(irealb://[^"\s<]+)')


def _extract_irealb_uri(html: str) -> str | None:
    """Pull the first irealb:// URI from a playlist HTML page.

    iRealPro's "Share Playlist" output puts the URI in an ``<a href="...">``
    on one long line; the regex captures everything up to the closing
    quote/whitespace/angle bracket.
    """
    match = _IREALB_URI_RE.search(html)
    return match.group(1) if match else None


def _parse_uri(uri: str) -> list[ParsedSong]:
    """Deobfuscate via pyRealParser, then map to our dataclasses."""
    # Local import keeps the rest of the module testable without the
    # third-party dependency installed (useful for normalize_chord_symbol
    # tests).
    from pyRealParser import Tune

    raw_tunes = Tune.parse_ireal_url(uri)
    parsed: list[ParsedSong] = []
    for raw in raw_tunes:
        try:
            ps = _map_tune(raw)
        except _SkippableTune:
            # Known no-op — e.g. playlist-name marker pyRealParser
            # surfaces as a "tune" with no chord content.
            continue
        if ps is not None:
            parsed.append(ps)
    return parsed


class _SkippableTune(Exception):
    """Raised when a pyRealParser ``Tune`` is structurally not a real song."""


def _map_tune(raw) -> ParsedSong | None:
    """Convert a pyRealParser ``Tune`` to our ``ParsedSong``."""
    title = (raw.title or "").strip()
    chord_string = getattr(raw, "chord_string", "") or ""
    if not title or not chord_string.strip():
        # Playlist-name marker or otherwise empty — skip silently
        raise _SkippableTune()

    composer = (raw.composer or "").strip()
    style = (raw.style or "").strip()
    key = (raw.key or "").strip()

    # pyRealParser returns time_signature as a tuple (num, den)
    ts_tuple = getattr(raw, "time_signature", None) or (4, 4)
    if isinstance(ts_tuple, tuple) and len(ts_tuple) == 2:
        time_signature = f"{ts_tuple[0]}/{ts_tuple[1]}"
    else:
        # Fallback for unexpected shapes — preserve as string
        time_signature = str(ts_tuple) if ts_tuple else "4/4"

    bpm = getattr(raw, "bpm", None)
    tempo_bpm = int(bpm) if bpm else None
    if tempo_bpm == 0:
        # iRealPro encodes "no tempo specified" as 0 — normalize to None
        tempo_bpm = None

    measures_as_strings = list(getattr(raw, "measures_as_strings", []) or [])
    if not measures_as_strings:
        raise _SkippableTune()

    beats_per_measure = ts_tuple[0] if isinstance(ts_tuple, tuple) else 4

    sections, warnings = _build_sections(
        chord_string=chord_string,
        measures_as_strings=measures_as_strings,
        beats_per_measure=beats_per_measure,
    )

    return ParsedSong(
        title=title,
        composer=composer,
        style=style,
        key=key,
        time_signature=time_signature,
        tempo_bpm=tempo_bpm,
        sections=tuple(sections),
        warnings=tuple(warnings),
    )


# Section labels in chord_string look like '*A', '*B', '*C', etc.
_SECTION_MARKER_RE = re.compile(r"\*([A-Za-z])")


def _build_sections(
    chord_string: str,
    measures_as_strings: list[str],
    beats_per_measure: int,
) -> tuple[list[ParsedSection], list[str]]:
    """Recover section structure from the chord_string + per-measure flat list.

    Strategy:
    - Walk chord_string left to right. Each ``*X`` marker opens a new
      section labeled ``X``. Each ``|`` between markers (or until the
      next ``*X``) is one bar boundary.
    - Count bars per section in chord_string order.
    - Slice ``measures_as_strings`` into per-section chunks using those
      counts.

    pyRealParser has already expanded repeats inside the section
    contents and across section repeats — so we trust
    ``measures_as_strings`` as the played sequence and just use
    chord_string for the section boundaries.

    Returns (sections, warnings).
    """
    warnings: list[str] = []

    # Extract (section_label, bar_count) by scanning chord_string
    section_layout: list[tuple[str, int]] = []
    current_label: str | None = None
    current_count = 0

    # Strip pyRealParser's internal tokens that don't represent bars:
    # T44/T34 etc (time-sig), section [] brackets, N1/N2 (endings), etc.
    # We only count '|' characters between section markers + handle the
    # trailing measure (chord_string usually doesn't end with '|').
    cleaned = chord_string

    pos = 0
    while pos < len(cleaned):
        m = _SECTION_MARKER_RE.match(cleaned, pos)
        if m:
            # Close out the previous section. '|' is a separator between
            # bars, not a terminator after each bar, so a section with N
            # '|' characters contains N+1 bars.
            if current_label is not None:
                section_layout.append((current_label, current_count + 1))
            current_label = m.group(1)
            current_count = 0
            pos = m.end()
            continue
        if cleaned[pos] == "|":
            current_count += 1
        pos += 1

    # Close out the final section. There's an implicit final bar without a
    # trailing '|', so add 1 to capture it.
    if current_label is not None:
        section_layout.append((current_label, current_count + 1))

    if not section_layout:
        # No section markers at all — treat the whole song as one
        # unlabeled section. This shouldn't happen in well-formed
        # iRealPro charts but keep it from crashing the import.
        section_layout = [("", len(measures_as_strings))]
        warnings.append("no section markers found; treating as single section")

    # Slice measures_as_strings into section chunks
    sections: list[ParsedSection] = []
    cursor = 0
    total_measures = len(measures_as_strings)
    for order, (label, bar_count) in enumerate(section_layout):
        chunk = measures_as_strings[cursor : cursor + bar_count]
        cursor += bar_count
        measures = _build_measures(chunk, beats_per_measure, warnings)
        sections.append(
            ParsedSection(
                label=label,
                order_index=order,
                measures=tuple(measures),
            )
        )

    if cursor != total_measures:
        warnings.append(
            f"section bar-count sum ({cursor}) != measures_as_strings ({total_measures}); "
            f"some bars may be misassigned. layout={section_layout}"
        )

    return sections, warnings


def _build_measures(
    measure_strings: list[str],
    beats_per_measure: int,
    warnings: list[str],
) -> list[ParsedMeasure]:
    """Convert per-measure strings to ParsedMeasure with chord events."""
    out: list[ParsedMeasure] = []
    for i, raw_measure in enumerate(measure_strings, start=1):
        events = split_measure_chord_events(raw_measure, beats_per_measure)
        chord_events: list[ParsedChordEvent] = []
        for beat, raw_chord in events:
            normalized = normalize_chord_symbol(raw_chord)
            if normalized.warning:
                warnings.append(
                    f"measure {i}: normalize warning {normalized.warning} "
                    f"(raw={raw_chord!r})"
                )
            chord_events.append(
                ParsedChordEvent(beat=beat, chord=normalized)
            )
        out.append(
            ParsedMeasure(
                number_in_section=i,
                chord_events=tuple(chord_events),
            )
        )
    return out


__all__ = [
    "ParsedChordEvent",
    "ParsedMeasure",
    "ParsedSection",
    "ParsedSong",
    "parse_playlist_html",
    "parse_single_uri",
]
