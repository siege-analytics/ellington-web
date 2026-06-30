"""Audio-detection ↔ chart-slice alignment for the practice-feedback loop.

This is the bridge between the audio side (Recording → detected chord
sequence via madmom / Chordino / Essentia — #86, not yet shipped) and
the chart side (Song → Slices → fired rules — #178/#180/#182).

The function takes a pre-computed detection list — no audio decoding,
no chord inference, just timing arithmetic + quality comparison.
When #86 lands, the wire-up is one function call:

    detections = run_detection(recording)  # #86
    slices = list(slices_for_song(song))   # #180
    aligned = align_detections(
        detections, slices,
        song_seconds=recording.duration_s,
        tempo_bpm=song.default_tempo_bpm or 120,
    )
    # Pass aligned to conformance (next ticket): each AlignedSlice
    # carries its slice's fired rules + the detection that sounded
    # against it, ready for per-rule verdict emission.

## Stub: defers tempo-tracking / beat-aware alignment to v2.

v1 makes two simplifying assumptions:
1. Recording starts at song-second 0 (no count-in handling)
2. Tempo is rigid at the song's default BPM throughout

Cost of these stubs:
- A recording with significant tempo drift will produce false 'none'
  match_kinds in the drift region
- A count-in / pickup will shift every alignment by N beats

Both are acceptable v1 cost — beat-tracking belongs in #86 (detection
pipeline) or a tempo-tracker that emits a piecewise-linear tempo map.
Once that's available, ``align_detections`` takes the tempo map as
input and the timing math becomes drift-aware. Defer ratified per
cross-agent ack 2026-06-24 (engine agent: "ship the alignment-contract
code path with stub inputs, unit-test it, leave the audio wire-up to
follow").

Refs: ellington-web #184 (this), #178 (firing engine), #180 (slicer),
#86 (chord detection — emits the input format), #60 epic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from apps.engine_rules.firing import (
    Slice,
    augment_chord_quality,
    family_of,
)


MatchKind = Literal["exact", "family", "none"]


@dataclass
class DetectedChord:
    """One chord-detection event from the audio pipeline.

    Emitted by #86 chord detection (madmom / Chordino / Essentia, TBD).
    The shape is intentionally library-agnostic — alignment doesn't
    care which inference library produced the tuple.
    """

    start_s: float
    end_s: float
    chord_symbol: str
    confidence: float = 1.0

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


@dataclass
class AlignedSlice:
    """One (Slice, DetectedChord-or-None) pair for conformance.

    The unit conformance consumes — given the slice's fired rules
    (from fire_all) AND what the player actually played in the same
    time window (the detection), conformance emits per-fired-rule
    verdicts. v1 is "quality match" — voicing match is harder, deferred.
    """

    slice: Slice
    detected: Optional[DetectedChord]
    match_kind: MatchKind
    confidence: float
    # The slice's expected time window in the recording (start, end)
    # — useful for the conformance UI to render the audio waveform
    # region next to the verdict.
    expected_start_s: float
    expected_end_s: float


def _slice_time_ranges(
    slices: list[Slice],
    *,
    tempo_bpm: float,
) -> list[tuple[float, float]]:
    """Compute each slice's expected (start_s, end_s) in the recording.

    v1 assumes rigid tempo at ``tempo_bpm`` and the recording starting
    at song-second 0. Time is accumulated linearly across slices using
    the duration each chord 'sounds for' implied by the next chord's
    beat position.

    The slice's ``beat_in_measure`` indexes its position within its
    measure; we infer 'beats until next chord' by subtracting from the
    next slice's beat_in_measure (wrapping at measure boundaries via
    the time_signature numerator).
    """
    if not slices:
        return []
    seconds_per_beat = 60.0 / max(tempo_bpm, 1.0)

    # Walk slices, accumulating elapsed beats. For each slice, the
    # "beats this chord sounds for" is the gap to the next slice
    # (intra-measure delta) or the remainder of the current measure
    # plus the next measure's intro beats (cross-measure).
    ranges: list[tuple[float, float]] = []
    elapsed_beats = 0.0
    for i, slice_ in enumerate(slices):
        start_beats = elapsed_beats
        if i + 1 < len(slices):
            next_slice = slices[i + 1]
            # Same-measure: next.beat_in_measure > current.beat_in_measure
            # Cross-measure: next.beat_in_measure <= current
            beats_per_measure = _beats_per_measure(slice_.time_signature)
            cur_beat = float(slice_.beat_in_measure or 1.0)
            next_beat = float(next_slice.beat_in_measure or 1.0)
            if next_beat > cur_beat:
                duration_beats = next_beat - cur_beat
            else:
                # Crossed a measure — fill the rest of this measure +
                # the intro of the next measure.
                duration_beats = (beats_per_measure - cur_beat + 1.0) + (
                    next_beat - 1.0
                )
        else:
            # Last slice: assume it sounds for the rest of its measure.
            beats_per_measure = _beats_per_measure(slice_.time_signature)
            cur_beat = float(slice_.beat_in_measure or 1.0)
            duration_beats = beats_per_measure - cur_beat + 1.0

        elapsed_beats = start_beats + duration_beats
        ranges.append((
            start_beats * seconds_per_beat,
            elapsed_beats * seconds_per_beat,
        ))
    return ranges


def _beats_per_measure(time_signature: Optional[str]) -> float:
    """Parse '4/4' / '3/4' / etc; default to 4 on parse failure."""
    if not time_signature:
        return 4.0
    try:
        numerator = time_signature.split("/", 1)[0]
        return float(numerator)
    except (ValueError, IndexError):
        return 4.0


def _overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


_ROOT_PATTERN = __import__("re").compile(r"^([A-G][#b]?)")


def _root_of(chord_symbol: str) -> Optional[str]:
    """Extract the root letter (with accidental) from a chord symbol.

    Returns None if no root prefix matches (e.g. 'NC' / empty / garbage).
    Normalizes sharps to lowercase 'b' (no — keeps source case so 'Bb'
    stays 'Bb'; the comparator's job is to compare these as-is given
    that the chart layer already canonicalizes roots).
    """
    if not chord_symbol:
        return None
    match = _ROOT_PATTERN.match(chord_symbol.strip())
    return match.group(1) if match else None


def _classify_match(
    slice_chord: str, slice_quality: str,
    detected_chord: str, detected_quality: str,
) -> MatchKind:
    """Match the slice's expected chord against what the player played.

    Different roots → ``"none"`` regardless of quality (Bm7 vs Dm7 are
    both min7 by quality but they're different chords). Same root +
    same canonical quality → ``"exact"``. Same root + same family →
    ``"family"``. ``"any"`` quality on either side short-circuits to
    exact (caller has signaled don't-care).
    """
    if slice_quality == "any" or detected_quality == "any":
        return "exact"

    slice_root = _root_of(slice_chord)
    detected_root = _root_of(detected_chord)
    if slice_root is None or detected_root is None:
        return "none"
    if slice_root != detected_root:
        return "none"
    if slice_quality == detected_quality:
        return "exact"
    if family_of(slice_quality) == family_of(detected_quality):
        return "family"
    return "none"


def align_detections(
    detections: Iterable[DetectedChord],
    slices: list[Slice],
    *,
    tempo_bpm: float = 120.0,
    song_seconds: Optional[float] = None,
) -> list[AlignedSlice]:
    """Map each slice to the detection that sounds against it.

    For each slice, computes its expected time-range (rigid tempo v1),
    then picks the detection with the maximum overlap. If no detection
    overlaps the slice's window, emits AlignedSlice(detected=None,
    match_kind="none").

    Confidence is the detection's confidence scaled by the overlap
    fraction — a slice with 100% overlap to a 0.9-confidence detection
    gets confidence 0.9; a slice with 50% overlap gets 0.45.

    ``song_seconds`` is accepted but unused in v1 — kept in the
    signature so the next iteration (tempo-map-aware) can extend the
    contract without churn.
    """
    detections_list = list(detections)
    ranges = _slice_time_ranges(slices, tempo_bpm=tempo_bpm)
    aligned: list[AlignedSlice] = []

    for slice_, (start_s, end_s) in zip(slices, ranges):
        slice_quality = slice_.chord_quality or augment_chord_quality(
            slice_.target_chord_canonical
        )

        # Find detection with maximum overlap to this slice's window.
        best_detection: Optional[DetectedChord] = None
        best_overlap = 0.0
        for det in detections_list:
            overlap = _overlap_seconds(start_s, end_s, det.start_s, det.end_s)
            if overlap > best_overlap:
                best_overlap = overlap
                best_detection = det

        if best_detection is None or best_overlap <= 0:
            aligned.append(AlignedSlice(
                slice=slice_, detected=None, match_kind="none",
                confidence=0.0,
                expected_start_s=start_s, expected_end_s=end_s,
            ))
            continue

        detected_quality = augment_chord_quality(best_detection.chord_symbol)
        match_kind = _classify_match(
            slice_.target_chord_canonical, slice_quality,
            best_detection.chord_symbol, detected_quality,
        )
        slice_window = max(end_s - start_s, 0.001)
        overlap_fraction = min(1.0, best_overlap / slice_window)
        confidence = best_detection.confidence * overlap_fraction
        aligned.append(AlignedSlice(
            slice=slice_,
            detected=best_detection,
            match_kind=match_kind,
            confidence=confidence,
            expected_start_s=start_s,
            expected_end_s=end_s,
        ))

    return aligned


__all__ = [
    "DetectedChord",
    "AlignedSlice",
    "MatchKind",
    "align_detections",
]
