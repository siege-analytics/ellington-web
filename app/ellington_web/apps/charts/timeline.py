"""Chart-timeline math — pure-Python helpers that map between (measure, beat)
positions on a :class:`apps.charts.models.Song` and wall-clock seconds.

These functions are the alignment primitive between two streams:

  * **Ground-truth chord events** live in the chart side
    (``Song → Section → Measure → ChordEvent``). The ``Measure`` model
    indexes its position within a section; this module flattens the
    section/measure hierarchy into a song-wide ``flat_measure_index``
    so callers can reason in absolute position.
  * **Detected voicings** from sub-4's audio pipeline arrive with
    ``timestamp_ms``. The comparator needs to know *which measure* the
    user was playing at that moment to compare against the chart's
    chord at the same measure.

The functions here are pure — they don't touch the database beyond the
``Song`` instance the caller passes in. Designed to be called from the
comparator (to align ``DetectedVoicing.measure_index``), from sub-4 (to
window audio into per-measure chunks), and from the practice-flow UI
(to display "you're at bar 4" timing). Callers are responsible for
having a ``Song`` already loaded.

Tempo resolution priority (highest to lowest):

    1. The ``tempo_bpm`` argument explicitly passed in (per-recording
       override — what the user set when uploading the recording).
    2. ``Song.default_tempo_bpm`` — the chart's authored default.
    3. :data:`DEFAULT_TEMPO_BPM` — a sane fallback (120 BPM, the
       conventional "medium swing" pulse) so we never divide by zero
       and never need to ask the user a question to compute timeline
       math.

The time-signature denominator is treated as quarter-note = beat for
v0 — iRealPro doesn't produce compound-meter signatures like 6/8 in
practice, and adding denominator handling without a test corpus would
be speculative complexity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterator, NamedTuple

if TYPE_CHECKING:
    from .models import ChordEvent, Song


_log = logging.getLogger(__name__)


DEFAULT_TEMPO_BPM: int = 120
"""Used when neither the caller nor the ``Song`` specifies a tempo. 120
is the canonical "medium swing" pulse — wrong by an octave in either
direction is unusual but corrigible, while crashing on missing tempo
would block the whole loop."""


class FlatChordEvent(NamedTuple):
    """One ``ChordEvent`` annotated with its song-wide flat measure index.

    ``flat_measure_index`` is 1-indexed across the whole song (sections
    are flattened in ``order_index`` order). ``beat`` mirrors the
    underlying ``ChordEvent.beat`` (1-indexed: 1.0 = downbeat,
    2.5 = 'and' of beat 2, etc.). ``chord_event`` is the underlying
    ORM instance so callers retain access to the raw chord symbol and
    voicing reference.
    """

    flat_measure_index: int
    beat: float
    chord_event: "ChordEvent"


# ---------------------------------------------------------------------------
# Tempo + time-signature resolution
# ---------------------------------------------------------------------------


def resolve_tempo(song: "Song", override_tempo_bpm: int | None = None) -> int:
    """Tempo resolution: argument > Song default > :data:`DEFAULT_TEMPO_BPM`.

    Returns a strictly positive integer BPM. Logs at DEBUG when falling
    back to ``DEFAULT_TEMPO_BPM`` so operators can audit which charts
    are missing tempo.
    """
    if override_tempo_bpm is not None and override_tempo_bpm > 0:
        return int(override_tempo_bpm)
    song_default = getattr(song, "default_tempo_bpm", None)
    if song_default is not None and song_default > 0:
        return int(song_default)
    _log.debug(
        "tempo fallback to DEFAULT_TEMPO_BPM=%d for song %r",
        DEFAULT_TEMPO_BPM,
        getattr(song, "slug", "<unknown>"),
    )
    return DEFAULT_TEMPO_BPM


def beats_per_measure(song: "Song") -> int:
    """Parse the time-signature numerator from ``Song.time_signature``.

    Defaults to 4 when the time signature is missing or malformed.
    Treats denominator as quarter-note = beat for v0 (see module
    docstring for rationale).
    """
    ts = getattr(song, "time_signature", None) or "4/4"
    try:
        numerator_str = ts.split("/", 1)[0].strip()
        n = int(numerator_str)
        if n > 0:
            return n
    except (ValueError, AttributeError):
        pass
    return 4


# ---------------------------------------------------------------------------
# Position ↔ time conversions
# ---------------------------------------------------------------------------


def measure_to_seconds(
    song: "Song",
    flat_measure_index: int,
    beat: float = 1.0,
    tempo_bpm: int | None = None,
) -> float:
    """Wall-clock seconds for a given (flat_measure_index, beat) position.

    ``flat_measure_index`` is 1-indexed across the whole song. ``beat``
    is 1-indexed within the measure (1.0 = downbeat). Returns 0.0 for
    the song's downbeat (measure=1, beat=1).

    Formula::

        beat_position = (flat_measure_index - 1) * bpm + (beat - 1.0)
        seconds       = beat_position * (60.0 / tempo_bpm)

    where ``bpm`` is :func:`beats_per_measure` and ``tempo_bpm`` is
    :func:`resolve_tempo`.
    """
    if flat_measure_index < 1:
        raise ValueError(
            f"flat_measure_index must be >= 1, got {flat_measure_index}"
        )
    tempo = resolve_tempo(song, tempo_bpm)
    bpm_count = beats_per_measure(song)
    beat_position = (flat_measure_index - 1) * bpm_count + (beat - 1.0)
    return beat_position * (60.0 / tempo)


def seconds_to_measure(
    song: "Song",
    seconds: float,
    tempo_bpm: int | None = None,
) -> tuple[int, float]:
    """Reverse of :func:`measure_to_seconds`.

    Returns ``(flat_measure_index, beat)`` for the given wall-clock
    seconds. The downbeat (``seconds=0``) maps to ``(1, 1.0)``. Beat
    fractions reflect sub-beat resolution — the caller can floor to
    integers if they only care about the bar.

    Negative seconds are clamped to ``(1, 1.0)`` rather than raising;
    audio detectors occasionally emit slightly-negative timestamps near
    the song's start due to alignment slop.
    """
    if seconds < 0:
        return (1, 1.0)
    tempo = resolve_tempo(song, tempo_bpm)
    bpm_count = beats_per_measure(song)
    beat_position = seconds * (tempo / 60.0)
    flat_measure_index = int(beat_position // bpm_count) + 1
    beat = (beat_position % bpm_count) + 1.0
    return (flat_measure_index, beat)


# ---------------------------------------------------------------------------
# Flattening: walk the section/measure hierarchy in play order
# ---------------------------------------------------------------------------


def flatten_chord_events(song: "Song") -> Iterator[FlatChordEvent]:
    """Walk ``Song → Section → Measure → ChordEvent`` in play order.

    Yields :class:`FlatChordEvent` tuples with the song-wide flat
    measure index, beat position, and the underlying ChordEvent. Section
    labels are discarded — flattening is by ``Section.order_index`` then
    ``Measure.number_in_section`` then ``ChordEvent.beat`` — which gives
    callers an absolute timeline they can compare against detected audio
    positions.

    Lazy: returns an iterator so callers can short-circuit if they only
    want the first N events (e.g. checking a single measure during
    debugging).
    """
    flat_index = 0
    # Use the related-manager directly so the caller can hand us a Song
    # with prefetched sections/measures/chord_events if they need
    # query-count control.
    for section in song.sections.order_by("order_index"):
        for measure in section.measures.order_by("number_in_section"):
            flat_index += 1
            for event in measure.chord_events.order_by("beat"):
                yield FlatChordEvent(
                    flat_measure_index=flat_index,
                    beat=float(event.beat),
                    chord_event=event,
                )


def song_duration_seconds(song: "Song", tempo_bpm: int | None = None) -> float:
    """Total wall-clock duration of the song at the resolved tempo.

    Counts measures across all sections × :func:`beats_per_measure` ×
    seconds-per-beat. Returns ``0.0`` for a song with no sections or no
    measures.
    """
    tempo = resolve_tempo(song, tempo_bpm)
    bpm_count = beats_per_measure(song)
    total_measures = 0
    for section in song.sections.all():
        # Use the section's measure relation count rather than
        # measure_count field, since the latter is allowed to be None
        # (the ingest path may not fill it).
        total_measures += section.measures.count()
    if total_measures == 0:
        return 0.0
    total_beats = total_measures * bpm_count
    return total_beats * (60.0 / tempo)


__all__ = [
    "DEFAULT_TEMPO_BPM",
    "FlatChordEvent",
    "beats_per_measure",
    "flatten_chord_events",
    "measure_to_seconds",
    "resolve_tempo",
    "seconds_to_measure",
    "song_duration_seconds",
]
