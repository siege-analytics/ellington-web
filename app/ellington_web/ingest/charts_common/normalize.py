"""Format-agnostic canonical chord vocabulary used by every chart adapter.

Each source format (iRealPro, MuseScore, future BiaB / OMR) maps its
own notation into the :class:`NormalizedChord` shape so the comparator
matches one canonical chord-symbol string regardless of provenance.

This module is intentionally narrow: it owns the *canonical* end of
the pipeline only.

- ``NormalizedChord`` — the canonical dataclass every adapter emits.
- ``canonical_root`` — ASCII-normalize a root-note string (handles
  music21's ``B-`` and iRealPro's ``B♭`` → ``Bb``).
- ``canonicalize_chord_parts`` — assemble a ``NormalizedChord`` from
  already-split root / quality / alterations / bass parts. Callers
  with structured access (music21's ``ChordSymbol.root()`` /
  ``chordKind``, BiaB's chord struct) use this.

Dialect-specific string parsers (iRealPro's ``-^7`` → ``m-maj7``
quality table; pyRealParser's multi-chord measure-string splitter)
live in their owning adapter modules, not here. The original lift
in #73 over-included that code; the plugin-agent review on PR #74
flagged it and we split it back out so the canonical layer stays
free of any one format's quirks.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedChord:
    """Outcome of normalizing one chord symbol into canonical form.

    ``canonical`` is the form the comparator matches against (e.g.
    ``Cmaj7``, ``Bb7b9``, ``Am7b5``). ``raw`` preserves whatever the
    source format wrote verbatim (kept for debugging and future
    re-normalization passes). ``bass`` is the slash-chord bass note
    when present, else ``None``.
    """

    canonical: str
    raw: str
    bass: str | None = None
    """Slash-chord bass note (e.g. ``'G'`` for ``Cmaj7/G``). The
    canonical form does NOT include the bass — that lives here so the
    comparator can decide whether to ignore it (matching on quality
    only) or treat it as significant (inversion-aware critique)."""

    warning: str | None = None
    """Non-empty when the adapter couldn't fully canonicalize the raw
    symbol (unknown extension, malformed string, …). The canonical
    form is best-effort in those cases; callers should surface this to
    the import log so corpus-coverage gaps are visible.
    """


def canonical_root(raw_root: str) -> str:
    """Normalize a root-note string to the canonical ASCII form.

    music21 spells flats as ``-`` (e.g. ``B-``); iRealPro uses Unicode
    ``♭`` / ``♯`` or ASCII ``b`` / ``#``. The canonical form is ASCII
    ``b`` / ``#`` so the comparator's ``chord_symbol`` equality check
    passes regardless of source.
    """
    return (
        (raw_root or "")
        .replace("-", "b")
        .replace("♯", "#")
        .replace("♭", "b")
        .strip()
    )


def canonicalize_chord_parts(
    *,
    root: str,
    quality: str,
    alterations: str = "",
    bass: str | None = None,
    raw: str = "",
) -> NormalizedChord:
    """Assemble a ``NormalizedChord`` from already-split chord parts.

    For callers that already have root / quality / bass split (e.g. via
    ``music21.harmony.ChordSymbol`` accessors), bypassing the
    iRealPro-string parse keeps the canonical layer dialect-agnostic.
    ``quality`` should already be in the canonical vocabulary
    (``""``, ``m``, ``7``, ``maj7``, ``m7``, ``m7b5``, ``dim7``,
    ``m-maj7``, ``7#5``, …); callers are responsible for mapping
    their source notation to it.

    ``raw`` is the original source-format symbol kept for provenance.
    ``bass`` runs through the same ASCII-flat/sharp rules as the root,
    and is dropped (set to ``None``) when it equals the root after
    normalization — music21 sets ``bass()==root()`` for non-slash
    chords, and the comparator treats that as no slash.
    """
    canon_root = canonical_root(root)
    canon_bass = canonical_root(bass) if bass else None
    if canon_bass == canon_root:
        canon_bass = None
    canonical = canon_root + quality + alterations
    return NormalizedChord(
        canonical=canonical,
        raw=raw or canonical,
        bass=canon_bass,
    )


__all__ = [
    "NormalizedChord",
    "canonical_root",
    "canonicalize_chord_parts",
]
