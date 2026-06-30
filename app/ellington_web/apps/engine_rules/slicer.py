"""Slice production from apps.charts.Song for the firing engine.

Walks Section → Measure → ChordEvent in form-order and yields one
``Slice`` per ChordEvent with prev/next chord lookups, augmented with
``chord_quality`` etc. per ``firing.augment()``.

The firing engine (#177) consumes these Slices; this module is the
producer half of the chart-side firing pipeline. Recording-side
conformance (#86 + alignment) is downstream of firing and not the
slicer's concern.

v0.1 behavior:
- Linear traversal as the chord-events are stored — repeats are NOT
  expanded (first-ending / second-ending / open / close markers are
  ignored). v0.2 may add repeat-aware expansion.
- Application-context dimensions (arrangement.style, progression.*)
  stay ``None`` — those come from session context when the comparator
  fires (#71) or from a future authoring layer.
- ChordEvents with empty chord_symbol are skipped (placeholder rows).

Augmented-facet inference (``scale.context``, ``harmonic.context``)
intentionally stops at a stub per cross-agent ack 2026-06-24. The
firing spec §3 is informal on inference algorithms ("MAY grow");
plugin agent is authoring a §3.1 inference-algorithm appendix as the
single source of truth. Until that lands:

- ``scale.context`` stays None — corpus usage is 10 rules (8 Goodrick);
  rules requiring a literal value won't fire, rules using ``"any"``
  still fire normally. Acceptable cost for v0.1 shipping.
- ``harmonic.context`` covers progression.position ∈ {I, vi, IIImaj,
  V, ii, IV} → {tonic, dominant_function, subdominant_function}; the
  passing/tension buckets stay None. Corpus usage is 188 rules
  (Laukens 99, Harris 32, Pass 22, Roberts 26); the canonical-position
  cases catch ~80%. Rule authors who need guaranteed firing should
  write ``"any"`` for these dimensions in the rule's ``when`` block
  rather than a literal value.

When the §3.1 appendix lands the inference algorithm will be ported
verbatim, likely extracted into ``apps/engine_rules/inference.py``.

Caller is responsible for prefetching related sections / measures /
chord_events to avoid N+1 queries. The typical usage:

    song = Song.objects.prefetch_related(
        "sections__measures__chord_events"
    ).get(slug="all-the-things")
    for slice_ in slices_for_song(song):
        for rule_fire in fire_all(rules, slice_):
            ...

Refs: ellington-web #180 (this), #177 (firing engine), #60 epic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Optional

from apps.engine_rules.firing import Slice, augment

if TYPE_CHECKING:
    from apps.charts.models import Song  # pragma: no cover


def slices_for_song(song: "Song") -> Iterator[Slice]:
    """Yield one augmented Slice per ChordEvent in the song's form order.

    Iterates Section → Measure → ChordEvent following each model's
    ordering meta (Section.order_index, Measure.number_in_section,
    ChordEvent.beat). prev / next chord lookups span the entire linear
    chord stream — they cross section and measure boundaries.

    Empty chord_symbol rows are skipped. Songs with zero ChordEvents
    yield an empty iterator (not an error).
    """
    # Linearize the chord stream first so prev/next lookups are O(1)
    # and we don't traverse related sets multiple times. Each tuple
    # is (chord_symbol, section, measure, chord_event_beat) — we
    # need the parent objects for section_label + time_signature.
    linear: list[tuple] = []
    for section in song.sections.all():
        for measure in section.measures.all():
            for chord_event in measure.chord_events.all():
                symbol = (chord_event.chord_symbol or "").strip()
                if not symbol:
                    continue
                linear.append((symbol, section, measure, chord_event))

    default_time_signature = song.time_signature or "4/4"

    for i, (symbol, section, measure, chord_event) in enumerate(linear):
        prev_symbol: Optional[str] = (
            linear[i - 1][0] if i > 0 else None
        )
        next_symbol: Optional[str] = (
            linear[i + 1][0] if i + 1 < len(linear) else None
        )
        time_signature = (
            measure.time_signature_override or default_time_signature
        )
        slice_ = Slice(
            target_chord_canonical=symbol,
            prev_chord_canonical=prev_symbol,
            next_chord_canonical=next_symbol,
            key=song.key or None,
            section_label=section.label,
            beat_in_measure=float(chord_event.beat),
            time_signature=time_signature,
        )
        yield augment(slice_)


__all__ = ["slices_for_song"]
