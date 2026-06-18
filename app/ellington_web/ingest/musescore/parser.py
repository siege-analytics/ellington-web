"""MuseScore .mscz / MusicXML parser — produces ``ParsedSong`` dataclasses.

Mirrors the dataclass shape of :mod:`ingest.irealpro.parser` so the
importer can write ``apps.charts`` rows without knowing the source
format. The iRealPro path's ``ParsedSong``/``ParsedSection``/etc. lives
in its own module for now — Phase 4-MS keeps a parallel set here
because the two formats may diverge in what they capture (e.g.
MuseScore-only ``DetectedVoicing`` hooks in Phase 4-MS-followup). If
the dataclasses stay structurally identical past Phase 4-MS we'll lift
them into ``ingest.charts_common`` too.

Format handling:

- ``.mscz`` (the MuseScore archive) is converted to MusicXML via the
  ``mscore`` (MuseScore Studio) CLI, then parsed with ``music21``.
  ``music21`` does not natively read ``.mscz`` — internally it shells
  out to the same CLI, which fails opaquely if MuseScore isn't on
  ``PATH``. We invoke the CLI ourselves so the failure mode is
  ``MuseScoreNotFoundError`` with an actionable message.
- ``.musicxml`` / ``.xml`` is fed directly to ``music21`` (the
  omr-leadsheet pipeline already produces MusicXML alongside its .mscz
  output, so Phase 4-PDF can skip the mscore round-trip).

Section detection (decided in #73):

1. ``RehearsalMark`` (e.g. ``'A'``, ``'B'``, ``'Bridge'``) — primary.
2. ``SystemLayout`` system-break — fallback when no rehearsal marks
   are present (chord-melody arrangements often skip them).
3. Single unlabeled section — if neither signal is present, we still
   want a complete timeline.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .normalize import normalize_music21_chord_symbol

if TYPE_CHECKING:
    from music21.stream import Score  # pragma: no cover

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Frozen typed shape (mirrors ingest.irealpro.parser)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedChordEvent:
    """One chord at a specific beat within a measure (1-indexed beat)."""

    beat: float
    chord: object  # NormalizedChord — duck-typed to avoid cross-package coupling


@dataclass(frozen=True)
class ParsedMeasure:
    """One bar, 1-indexed within its section."""

    number_in_section: int
    chord_events: tuple[ParsedChordEvent, ...]


@dataclass(frozen=True)
class ParsedSection:
    """A formal section (A, B, Bridge, …) of a song."""

    label: str
    order_index: int
    measures: tuple[ParsedMeasure, ...]


@dataclass(frozen=True)
class ParsedSong:
    title: str
    composer: str
    style: str  # MuseScore doesn't carry a 'style' field; left empty for now
    key: str
    time_signature: str
    tempo_bpm: int | None
    sections: tuple[ParsedSection, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


class MuseScoreNotFoundError(RuntimeError):
    """Raised when ``.mscz`` input is given but the ``mscore`` CLI is absent.

    Installs are platform-specific (Homebrew ``brew install musescore``
    on macOS; ``apt install musescore`` on Debian). Surfacing this
    explicitly rather than letting ``music21`` swallow it keeps the
    user-facing error message actionable.
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


# Pass-2 fallback floor (see ``_detect_section_boundaries``). Tunes
# with more system-breaks than this many *post-initial* break events
# are treated as having no meaningful section structure rather than
# being chopped into N tiny one-bar sections — typical chord-melody
# arrangements with one chord per system would otherwise produce
# pathological output.
_SYSTEM_BREAK_SECTION_CAP = 4

_MSCORE_ENV_VAR = "ELLINGTON_MSCORE_BIN"
_DEFAULT_MSCORE_CANDIDATES = (
    "mscore",
    "musescore",
    "mscore4",
    "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
)


def parse_path(path: str | os.PathLike[str]) -> list[ParsedSong]:
    """Parse one ``.mscz`` or ``.musicxml`` file into ``ParsedSong[]``.

    Returns a list because future MuseScore "album" formats may bundle
    multiple movements — every caller already iterates the result, so
    we don't constrain the public API to single-song.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    suffix = p.suffix.lower()
    if suffix == ".mscz":
        with _mscz_as_musicxml(p) as xml_path:
            score = _read_musicxml(xml_path)
    elif suffix in (".musicxml", ".xml"):
        score = _read_musicxml(p)
    else:
        raise ValueError(
            f"Unsupported MuseScore input extension {suffix!r} "
            f"(expected .mscz / .musicxml / .xml)"
        )
    return [_map_score(score)]


# ---------------------------------------------------------------------------
# Internals: .mscz → MusicXML
# ---------------------------------------------------------------------------


class _MuseScoreXmlContext:
    """Context manager: yields a path to the MusicXML derived from a .mscz.

    Cleans the temp file on exit. We use a class rather than an
    ``@contextmanager`` decorator because the CLI invocation needs
    explicit error handling that reads more cleanly as ``__enter__``.
    """

    def __init__(self, mscz_path: Path) -> None:
        self._mscz_path = mscz_path
        self._xml_path: Path | None = None

    def __enter__(self) -> Path:
        mscore = _find_mscore()
        if mscore is None:
            raise MuseScoreNotFoundError(
                "MuseScore CLI ('mscore' / 'musescore') not found on PATH. "
                "Install MuseScore Studio (https://musescore.org) or set "
                f"${_MSCORE_ENV_VAR} to the binary path. Required to "
                "convert .mscz to MusicXML; .musicxml input bypasses this."
            )
        # NamedTemporaryFile keeps the file handle open which mscore
        # can't write to on some platforms — mkstemp + close gives us
        # a clean path we own.
        fd, tmp = tempfile.mkstemp(suffix=".musicxml", prefix="ellington-mscore-")
        os.close(fd)
        self._xml_path = Path(tmp)
        try:
            # capture_output=True with text=False lets us defer decoding
            # so we can substitute on undecodable bytes — mscore on
            # non-UTF-8 locales (CP1252 etc.) otherwise crashes the
            # decode itself before we get to look at stderr.
            result = subprocess.run(
                [mscore, str(self._mscz_path), "-o", str(self._xml_path)],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            self._cleanup()
            raise RuntimeError(
                f"mscore conversion timed out after 60s for {self._mscz_path}"
            ) from exc
        stderr_raw = result.stderr or b""
        # Truncate to the first 2KB — mscore on some scores spits tens
        # of KB of MuseSampler warnings even on success, and we don't
        # want to flood the error message.
        stderr = stderr_raw[:2048].decode("utf-8", errors="replace").strip()
        if len(stderr_raw) > 2048:
            stderr += f" ... (truncated, {len(stderr_raw)} bytes total)"
        if not self._xml_path.exists():
            # Distinguish "ran but produced nothing" from "non-zero exit".
            # mscore is known to exit 0 even when the output path is
            # invalid (e.g. unwritable parent dir, malformed -o syntax)
            # so the exit code alone isn't sufficient.
            self._cleanup()
            raise RuntimeError(
                f"mscore exited {result.returncode} but produced no output "
                f"for {self._mscz_path}: {stderr or '(no stderr)'}"
            )
        if result.returncode != 0:
            self._cleanup()
            raise RuntimeError(
                f"mscore exited {result.returncode} converting "
                f"{self._mscz_path}: {stderr or '(no stderr)'}"
            )
        return self._xml_path

    def __exit__(self, exc_type, exc, tb) -> None:
        self._cleanup()

    def _cleanup(self) -> None:
        if self._xml_path is not None and self._xml_path.exists():
            try:
                self._xml_path.unlink()
            except OSError as exc:
                _log.warning(
                    "could not remove temp musicxml %s: %r",
                    self._xml_path,
                    exc,
                )


def _mscz_as_musicxml(mscz_path: Path) -> _MuseScoreXmlContext:
    return _MuseScoreXmlContext(mscz_path)


def _find_mscore() -> str | None:
    """Locate the ``mscore`` binary, honoring the override env var first.

    The env var lets tests inject a stub and lets ops point at a
    non-PATH install (the macOS ``.app`` bundle binary, an in-image
    install under ``/usr/lib/musescore`` on Debian, etc.).
    """
    override = os.environ.get(_MSCORE_ENV_VAR)
    if override:
        return override if Path(override).exists() else None
    for candidate in _DEFAULT_MSCORE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


# ---------------------------------------------------------------------------
# Internals: music21 Score → ParsedSong
# ---------------------------------------------------------------------------


def _read_musicxml(xml_path: Path) -> "Score":
    """Read MusicXML via music21, returning the parsed Score."""
    # Local import so the rest of the module is importable in environments
    # without music21 (e.g. unit tests of the dataclass shape alone).
    from music21 import converter

    return converter.parse(str(xml_path))


def _map_score(score: "Score") -> ParsedSong:
    """Convert a music21 ``Score`` to our ``ParsedSong`` dataclass."""
    from music21 import tempo as t_mod

    warnings: list[str] = []

    metadata = score.metadata
    title = (getattr(metadata, "title", None) or "").strip() or "(untitled)"
    composer = (getattr(metadata, "composer", None) or "").strip()

    # Time signature — first one found, defaults to 4/4
    flat = score.flatten()
    ts_list = list(flat.getElementsByClass("TimeSignature"))
    if ts_list:
        ts = ts_list[0]
        time_signature = ts.ratioString
        beats_per_measure = ts.numerator
        beat_quarter_length = 4.0 / ts.denominator
    else:
        time_signature = "4/4"
        beats_per_measure = 4
        beat_quarter_length = 1.0
        warnings.append("no TimeSignature found; defaulting to 4/4")

    # Tempo — first MetronomeMark found
    tempo_marks = list(flat.getElementsByClass(t_mod.MetronomeMark))
    tempo_bpm: int | None = None
    if tempo_marks and tempo_marks[0].number is not None:
        try:
            tempo_bpm = int(round(float(tempo_marks[0].number)))
        except (TypeError, ValueError):
            tempo_bpm = None

    # Key — derive from key signature on the first measure, fall back to "C".
    # music21 9.x: KeySignature.asKey() returns a Key; use Key.tonic.name (the
    # deprecated tonicPitchNameWithCase form is going away in 10.x). Mode is
    # not known from sharps alone — caller treats key as major-by-default.
    from music21 import exceptions21 as _m21_exc

    key_obj = next(iter(flat.getElementsByClass("KeySignature")), None)
    if key_obj is not None:
        try:
            key_str = key_obj.asKey().tonic.name
        except _m21_exc.Music21Exception:
            key_str = "C"
    else:
        key_str = "C"

    # Walk measures in the first part (lead-sheet convention: one part)
    parts = list(score.parts)
    if not parts:
        return ParsedSong(
            title=title,
            composer=composer,
            style="",
            key=key_str,
            time_signature=time_signature,
            tempo_bpm=tempo_bpm,
            sections=tuple(),
            warnings=tuple(warnings + ["score has no Parts"]),
        )
    part = parts[0]
    measures = list(part.getElementsByClass("Measure"))
    if not measures:
        return ParsedSong(
            title=title,
            composer=composer,
            style="",
            key=key_str,
            time_signature=time_signature,
            tempo_bpm=tempo_bpm,
            sections=tuple(),
            warnings=tuple(warnings + ["first part has no Measures"]),
        )

    # Section detection — rehearsal marks first, system breaks second,
    # single fall-through last (decided in #73).
    section_boundaries = _detect_section_boundaries(measures, warnings)

    sections = _build_sections(
        measures=measures,
        section_boundaries=section_boundaries,
        beat_quarter_length=beat_quarter_length,
        warnings=warnings,
    )

    return ParsedSong(
        title=title,
        composer=composer,
        style="",
        key=key_str,
        time_signature=time_signature,
        tempo_bpm=tempo_bpm,
        sections=tuple(sections),
        warnings=tuple(warnings),
    )


def _detect_section_boundaries(
    measures: list,
    warnings: list[str],
) -> list[tuple[int, str]]:
    """Return ``[(measure_index, label), ...]`` boundary list.

    ``measure_index`` is the 0-based index into ``measures`` where the
    section starts. The result always covers measure 0 — either with an
    explicit label or a synthetic one — so the caller can slice the
    measure list cleanly.
    """
    from music21.expressions import RehearsalMark
    from music21.layout import SystemLayout

    # Pass 1: rehearsal marks
    rehearsal: list[tuple[int, str]] = []
    for idx, m in enumerate(measures):
        for rm in m.getElementsByClass(RehearsalMark):
            label = (rm.content or "").strip()
            if label:
                rehearsal.append((idx, label))
                break  # only the first per measure
    if rehearsal:
        # Ensure measure 0 is covered — if the first rehearsal mark is
        # mid-piece, synthesize an "Intro" section for the prefix.
        if rehearsal[0][0] != 0:
            rehearsal.insert(0, (0, "Intro"))
        return rehearsal

    # Pass 2: system breaks. Lead-sheet convention is one system per
    # formal section; not always true, but a useful fallback when the
    # arranger didn't add rehearsal marks. Labels are synthesized.
    #
    # Floor (post-review on PR #74): chord-melody arrangements often
    # have one chord per system, which would degenerate this pass into
    # N single-bar "sections" for an N-bar tune. If we see more than
    # ``_SYSTEM_BREAK_SECTION_CAP`` system breaks, the arranger almost
    # certainly didn't intend those as formal-section boundaries and we
    # fall through to Pass 3 (single section) instead.
    breaks: list[tuple[int, str]] = []
    for idx, m in enumerate(measures):
        if list(m.getElementsByClass(SystemLayout)):
            breaks.append((idx, ""))
    if breaks:
        # Drop the first system-break if it's at measure 0 — every
        # piece starts with a system, that's not a section boundary.
        if breaks[0][0] == 0:
            breaks = breaks[1:]
        if breaks and len(breaks) <= _SYSTEM_BREAK_SECTION_CAP:
            # Label A, B, C, … in order; first section gets "A"
            labeled = [(0, "A")] + [
                (idx, chr(ord("A") + i + 1)) for i, (idx, _) in enumerate(breaks)
            ]
            warnings.append(
                "section labels synthesized from system breaks; no RehearsalMarks present"
            )
            return labeled
        if breaks:
            warnings.append(
                f"system-break count ({len(breaks) + 1}) exceeds floor "
                f"({_SYSTEM_BREAK_SECTION_CAP + 1}); falling through to single "
                "section. Almost certainly a chord-melody arrangement with one "
                "system per measure."
            )

    # Pass 3: single unlabeled section
    warnings.append(
        "no RehearsalMarks or system breaks; treating whole piece as one section"
    )
    return [(0, "")]


def _build_sections(
    *,
    measures: list,
    section_boundaries: list[tuple[int, str]],
    beat_quarter_length: float,
    warnings: list[str],
) -> list[ParsedSection]:
    """Slice the measure list at section boundaries and build dataclasses."""
    from music21 import harmony

    total = len(measures)
    sections: list[ParsedSection] = []
    for order, (start_idx, label) in enumerate(section_boundaries):
        end_idx = (
            section_boundaries[order + 1][0]
            if order + 1 < len(section_boundaries)
            else total
        )
        chunk = measures[start_idx:end_idx]
        parsed_measures: list[ParsedMeasure] = []
        for measure_pos, m in enumerate(chunk, start=1):
            chord_events: list[ParsedChordEvent] = []
            for cs in m.getElementsByClass(harmony.ChordSymbol):
                normalized = normalize_music21_chord_symbol(cs)
                if normalized.warning:
                    warnings.append(
                        f"section {label or '(unlabeled)'} m{measure_pos}: "
                        f"normalize warning {normalized.warning}"
                    )
                # music21 offset is in quarter notes from the start of
                # the measure. Convert to a 1-indexed beat:
                # beat = offset / beat_quarter_length + 1
                beat = float(cs.offset) / beat_quarter_length + 1.0
                chord_events.append(
                    ParsedChordEvent(beat=beat, chord=normalized)
                )
            chord_events.sort(key=lambda ev: ev.beat)
            parsed_measures.append(
                ParsedMeasure(
                    number_in_section=measure_pos,
                    chord_events=tuple(chord_events),
                )
            )
        sections.append(
            ParsedSection(
                label=label,
                order_index=order,
                measures=tuple(parsed_measures),
            )
        )
    return sections


__all__ = [
    "MuseScoreNotFoundError",
    "ParsedChordEvent",
    "ParsedMeasure",
    "ParsedSection",
    "ParsedSong",
    "parse_path",
]
