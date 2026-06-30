"""Song → MusicXML serializer (#236).

Converts a ``charts.Song`` into a MusicXML string that MuseScore can
play. The output is intentionally minimal — just chord symbols with
their durations + a time signature + a key + a tempo — because
MuseScore's playback engine voices the chord symbols according to
its own comping rules. We don't need to spell out notes; we just
need the harmony skeleton + tempo + meter, and MuseScore handles
the rest.

This is the canonical middle format for the audio epic (#232):
every chart-format adapter (.mscz / .ireal / .SGU) eventually
produces a Song; the Song goes through this serializer; the result
goes through MuseScore CLI for WAV render. One render path; three
ingest paths.

Per child #236 of #232.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.charts.models import Song


def song_to_musicxml(
    song: "Song",
    *,
    tempo_bpm: int | None = None,
    key: str | None = None,
) -> str:
    """Serialize a Song to a MusicXML string.

    Args:
        song: A charts.Song with sections + measures + chord_events
          populated.
        tempo_bpm: Override the song's default tempo (BPM).
        key: Override the song's key (e.g. 'C', 'Bb', 'F#m').

    Returns:
        MusicXML XML as a string (decoded utf-8). Suitable for
        writing to a ``.musicxml`` file before invoking ``mscore -o
        out.wav in.musicxml -s bank.sf3``.

    Raises:
        ValueError: if the song has no sections / measures.
    """
    # Import inside the function so import time of the audio module
    # doesn't pay the music21 import cost unless the serializer is
    # actually called (music21 imports are heavy).
    from music21 import (
        chord as m21_chord,
        harmony,
        key as m21_key,
        meter,
        note as m21_note,
        stream,
        tempo as m21_tempo,
    )

    sections = list(
        song.sections.order_by("order_index").prefetch_related(
            "measures__chord_events",
        )
    )
    if not sections:
        raise ValueError(f"Song {song.slug!r} has no sections — cannot serialize.")

    score = stream.Score()
    part = stream.Part()
    part.partName = song.title or song.slug

    effective_key = key or song.key or "C"
    effective_tempo = tempo_bpm or song.default_tempo_bpm or 120
    effective_meter = song.time_signature or "4/4"

    part.append(m21_key.Key(effective_key))
    part.append(meter.TimeSignature(effective_meter))
    part.append(m21_tempo.MetronomeMark(number=effective_tempo))

    measure_number = 1
    for section in sections:
        for measure in section.measures.all():
            m21_measure = stream.Measure(number=measure_number)
            measure_meter = (
                measure.time_signature_override or effective_meter
            )
            beats_per_measure = _parse_beats(measure_meter)

            # Collect chord events sorted by beat. Beats are 1-indexed
            # in the Django model; music21 offsets are 0-indexed.
            events = sorted(
                measure.chord_events.all(), key=lambda e: float(e.beat),
            )

            if not events:
                # Empty measure — fill with whole rest so MuseScore
                # doesn't collapse the measure to zero duration.
                m21_measure.append(m21_note.Rest(quarterLength=beats_per_measure))
            else:
                # If the first event isn't on beat 1, pad with a rest
                # from beat 1 up to the first event.
                first_beat = float(events[0].beat)
                if first_beat > 1.0:
                    m21_measure.append(
                        m21_note.Rest(quarterLength=first_beat - 1.0),
                    )

                for i, event in enumerate(events):
                    cs = harmony.ChordSymbol(event.chord_symbol)
                    # Duration: explicit value when set, else infer
                    # from the next event's beat (or the measure end).
                    if event.duration_beats is not None:
                        ql = float(event.duration_beats)
                    elif i + 1 < len(events):
                        ql = float(events[i + 1].beat) - float(event.beat)
                    else:
                        # Last event in the measure — sound through end
                        ql = beats_per_measure - (float(event.beat) - 1.0)
                    cs.quarterLength = max(ql, 0.25)  # avoid 0-len
                    m21_measure.append(cs)

            part.append(m21_measure)
            measure_number += 1

    score.append(part)

    # Write to a temp file via music21's exporter then read back. The
    # m21 API doesn't expose a clean string-render path so this is
    # the documented round-trip.
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".musicxml", delete=False,
    ) as tmp:
        score.write("musicxml", fp=tmp.name)
        out_path = Path(tmp.name)
    try:
        return out_path.read_text(encoding="utf-8")
    finally:
        out_path.unlink(missing_ok=True)


def _parse_beats(time_signature: str) -> float:
    """'4/4' → 4.0, '3/4' → 3.0, '6/8' → 6.0 (in eighths) → 3.0 quarter beats.

    For MusicXML purposes we want quarter-note count per measure.
    Common time signatures:
    - x/4 → x quarter notes
    - x/8 → x/2 quarter notes
    - x/2 → x*2 quarter notes
    """
    try:
        num_str, denom_str = time_signature.split("/")
        num, denom = int(num_str), int(denom_str)
    except (ValueError, AttributeError):
        return 4.0
    if denom == 4:
        return float(num)
    if denom == 8:
        return num / 2.0
    if denom == 2:
        return num * 2.0
    return 4.0
