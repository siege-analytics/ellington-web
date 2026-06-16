"""Map ``music21.harmony.ChordSymbol`` into the canonical chord vocabulary.

music21 already does the heavy lifting — it parses a MuseScore chord
figure (e.g. ``'B-7'``, ``'F#m7b5'``, ``'Cmaj7'``) into structured
``root() / chordKind / chord-step-modifications / bass()`` access. This
module's job is the *mapping* from music21's ``chordKind`` taxonomy
(``'major-seventh'``, ``'minor-seventh'``, ``'dominant-seventh'``, …)
to the short canonical quality tokens the comparator matches against
(``''``, ``'m'``, ``'7'``, ``'maj7'``, ``'m7'``, ``'dim7'``,
``'m7b5'``, ``'m-maj7'``, ``'7#5'``, …) and the propagation of
chord-step modifications (b5, #5, b9, #9, b13, …) into the canonical
suffix.

We deliberately do **not** re-parse the chord figure string — that
would just rebuild the lookup music21 already did. Everything routes
through :func:`ingest.charts_common.normalize.canonicalize_chord_parts`
so the canonical vocabulary stays consistent with the iRealPro path.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..charts_common.normalize import NormalizedChord, canonicalize_chord_parts

if TYPE_CHECKING:
    from music21.harmony import ChordSymbol  # pragma: no cover

_log = logging.getLogger(__name__)


# music21 ``chordKind`` → canonical quality token.
# Coverage chosen to cover the standard jazz lead-sheet vocabulary plus
# the rarer minor-major and augmented-seventh forms we see in
# chord-melody arrangements. Kinds not in this map fall through to the
# raw kind string with a warning so corpus-coverage gaps stay visible.
_KIND_TO_CANONICAL: dict[str, str] = {
    "major": "",
    "minor": "m",
    "augmented": "aug",
    "diminished": "dim",
    "dominant-seventh": "7",
    "major-seventh": "maj7",
    "minor-seventh": "m7",
    "diminished-seventh": "dim7",
    "half-diminished-seventh": "m7b5",
    "minor-major-seventh": "m-maj7",
    "augmented-seventh": "7#5",
    "major-sixth": "6",
    "minor-sixth": "m6",
    "dominant-ninth": "9",
    "major-ninth": "maj9",
    "minor-ninth": "m9",
    "dominant-11th": "11",
    "major-11th": "maj11",
    "minor-11th": "m11",
    "dominant-13th": "13",
    "major-13th": "maj13",
    "minor-13th": "m13",
    "suspended-fourth": "sus",
    "suspended-second": "sus2",
    "power": "5",
    "pedal": "",
}


# Chord-step modifier semantics: music21 represents alterations as
# (modType, degree, Interval). The Interval's ``directedName`` carries
# the size (e.g. ``'A1'`` for augmented unison up = sharp, ``'A-1'`` for
# augmented unison down = flat). We translate degree+direction to the
# canonical ``b``/``#`` notation the comparator's chord_symbol field
# uses.
def _alteration_token(modification) -> str | None:
    """Convert one ``ChordStepModification`` into a canonical suffix.

    Returns ``None`` if the modification can't be cleanly mapped — the
    caller surfaces an unmapped modification as a warning so corpus
    coverage gaps are auditable rather than silently dropped.
    """
    interval = getattr(modification, "interval", None)
    if interval is None:
        return None
    name = getattr(interval, "directedName", "") or ""
    degree = getattr(modification, "degree", None)
    if degree is None:
        return None
    # Augmented = sharp; diminished = flat. Direction (up vs down) on a
    # unison/octave flips the sign — A-1 is "augmented unison down" =
    # flat by a semitone, A1 is "augmented unison up" = sharp.
    is_flat = name.startswith("d") or name.startswith("A-")
    is_sharp = name.startswith("A") and not name.startswith("A-")
    if is_flat:
        return f"b{degree}"
    if is_sharp:
        return f"#{degree}"
    # Perfect/Major intervals on alteration are a no-op (the chord
    # tone is already where it should be); skip silently.
    return ""


def normalize_music21_chord_symbol(chord_symbol: "ChordSymbol") -> NormalizedChord:
    """Map one music21 ``ChordSymbol`` to a ``NormalizedChord``.

    Returns a ``NormalizedChord`` whose ``canonical`` form is what the
    comparator runs against and whose ``raw`` preserves the original
    MuseScore figure for debugging. When music21's ``chordKind`` isn't
    in our mapping, ``canonical`` falls back to the raw figure and a
    warning is attached — that keeps the chord visible in the timeline
    while flagging the gap for corpus expansion.
    """
    raw = (chord_symbol.figure or "").strip()

    root_obj = chord_symbol.root()
    if root_obj is None:
        return NormalizedChord(
            canonical=raw,
            raw=raw,
            warning=f"music21 ChordSymbol has no root: {raw!r}",
        )
    root_name = root_obj.name

    bass_obj = chord_symbol.bass()
    bass_name = bass_obj.name if bass_obj is not None else None

    kind = (chord_symbol.chordKind or "").strip()
    if kind == "none":
        # music21 emits 'none' when the figure is just a root with no
        # quality info — treat as a major triad, matching the iRealPro
        # path's "bare root → major triad" rule.
        quality = ""
    elif kind in _KIND_TO_CANONICAL:
        quality = _KIND_TO_CANONICAL[kind]
    else:
        # Unknown kind — fall back to raw figure, attach a warning so
        # the import log surfaces the gap. The chord still lands in the
        # timeline; the comparator just can't match on its quality.
        return NormalizedChord(
            canonical=raw or root_name,
            raw=raw,
            bass=bass_name if bass_name and bass_name != root_name else None,
            warning=f"unmapped music21 chordKind {kind!r} for {raw!r}",
        )

    # Stitch alterations after the quality token.
    alteration_parts: list[str] = []
    unmapped: list[str] = []
    for mod in chord_symbol.getChordStepModifications():
        token = _alteration_token(mod)
        if token is None:
            unmapped.append(repr(mod))
        elif token:
            alteration_parts.append(token)
    alterations = "".join(alteration_parts)

    normalized = canonicalize_chord_parts(
        root=root_name,
        quality=quality,
        alterations=alterations,
        bass=bass_name,
        raw=raw,
    )
    if unmapped:
        # Re-wrap with a warning while preserving the canonical form.
        return NormalizedChord(
            canonical=normalized.canonical,
            raw=normalized.raw,
            bass=normalized.bass,
            warning=f"unmapped chord-step modifications: {unmapped}",
        )
    return normalized


__all__ = ["normalize_music21_chord_symbol"]
