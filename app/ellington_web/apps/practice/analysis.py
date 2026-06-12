"""Audio analysis — Phase 3a scaffolding with a chart-matching placeholder.

The real chord-detection algorithm (madmom ``DeepChromaProcessor`` or
equivalent) lands in Phase 3b (#68 — separate ticket). This module
provides the **integration shape** so the worker → ChordDetection
write path can be reviewed independently of the algorithm choice.

The placeholder ``analyze_recording_placeholder`` reads the recording's
linked Song's chord progression and emits ``ChordDetection`` rows that
match the chart with ``confidence=1.0``. This is *obviously* not a
detection — it's a synthetic perfect-detection that makes the rest of
the pipeline (Recording.analysis_status transitions, comparator
hand-off, sub-5 prose render once it exists) exercisable end-to-end.

When Phase 3b lands, the placeholder is replaced by a real-detector
function with the same signature. Callers (the Celery task) don't
change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from apps.charts.models import Song

from .models import ChordDetection, Recording


# Inlined here (rather than imported from ``apps.charts.timeline``)
# because Phase 1b (#64) is in a separate PR that hasn't merged. After
# #64 merges, swap these for ``apps.charts.timeline.beats_per_measure``
# and ``apps.charts.timeline.resolve_tempo``.
_DEFAULT_TEMPO_BPM = 120


def _beats_per_measure(song: Song) -> int:
    ts = (song.time_signature or "4/4").split("/", 1)[0].strip()
    try:
        n = int(ts)
        return n if n > 0 else 4
    except ValueError:
        return 4


def _resolve_tempo(song: Song) -> int:
    if song.default_tempo_bpm and song.default_tempo_bpm > 0:
        return int(song.default_tempo_bpm)
    return _DEFAULT_TEMPO_BPM

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisOutcome:
    """Result of one analysis run — counters for the caller's log/UI."""

    detections_written: int
    duration_seconds_estimated: float
    """Total length of the analyzed audio in seconds. For the placeholder,
    derived from the song's bar count × tempo (since we haven't loaded
    the audio file). The real analyzer (Phase 3b) reads the recording
    file's actual duration."""

    notes: str = ""
    """Free-form notes for ops + the Recording.notes append."""


def analyze_recording_placeholder(recording: Recording) -> AnalysisOutcome:
    """Phase 3a placeholder: emit chart-matching ChordDetections.

    Wipes any existing ``ChordDetection`` rows for this recording (so
    re-analysis is idempotent), then walks the linked Song's chord
    progression and emits one detection per ``(measure, beat,
    chord_event)`` triple. Timing is derived from
    :func:`apps.charts.timeline` math given the recording's session
    tempo and the song's time signature.

    Returns an :class:`AnalysisOutcome` for the caller's logging.

    No file I/O — the placeholder doesn't read the actual audio. The
    real detector (Phase 3b) will read ``apps.practice.storage.absolute_path_for(recording.file_ref)``
    and run chord recognition on the audio samples.
    """
    session = recording.session
    song = session.song
    if song is None:
        # No chart linked — no ground truth to emit against. Real
        # detector handles this with actual recognition; placeholder
        # just no-ops.
        _log.info(
            "recording %d: no linked song; placeholder emits no detections",
            recording.id,
        )
        return AnalysisOutcome(
            detections_written=0,
            duration_seconds_estimated=0.0,
            notes="no linked song; nothing to emit",
        )

    # Clear out previous detections so re-analyze is destructive (per
    # the design — comparator should see at most one set of detections
    # per recording).
    ChordDetection.objects.filter(recording=recording).delete()

    tempo = _resolve_tempo(song)
    bpm_count = _beats_per_measure(song)
    seconds_per_beat = 60.0 / tempo

    detections: list[ChordDetection] = []
    flat_measure_index = 0
    for section in song.sections.order_by("order_index").prefetch_related(
        "measures__chord_events"
    ):
        for measure in section.measures.order_by("number_in_section"):
            flat_measure_index += 1
            for event in measure.chord_events.order_by("beat"):
                # (flat_measure - 1) full bars + (beat - 1) beats into
                # the current bar
                beat_position = (
                    (flat_measure_index - 1) * bpm_count + (float(event.beat) - 1.0)
                )
                timestamp_ms = int(beat_position * seconds_per_beat * 1000)
                detections.append(
                    ChordDetection(
                        recording=recording,
                        beat_timestamp_ms=timestamp_ms,
                        detected_chord_symbol=event.chord_symbol,
                        confidence=1.0,
                        voicing_style_tags=[],
                        detection_model_ref="placeholder:chart-mirror:v1",
                    )
                )

    if detections:
        ChordDetection.objects.bulk_create(detections)

    duration_estimate = 0.0
    if detections:
        # Last detection's timestamp + one bar of headroom is a
        # reasonable estimate of the audio duration in absence of
        # actually reading the file.
        last_ts_seconds = detections[-1].beat_timestamp_ms / 1000.0
        duration_estimate = last_ts_seconds + (bpm_count * seconds_per_beat)

    _log.info(
        "recording %d: placeholder wrote %d detections over ~%.1fs (tempo=%d)",
        recording.id,
        len(detections),
        duration_estimate,
        tempo,
    )
    return AnalysisOutcome(
        detections_written=len(detections),
        duration_seconds_estimated=duration_estimate,
        notes=(
            f"placeholder:chart-mirror:v1 wrote {len(detections)} "
            f"detections; tempo={tempo}bpm"
        ),
    )


__all__ = ["AnalysisOutcome", "analyze_recording_placeholder"]
