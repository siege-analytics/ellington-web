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

import re
from dataclasses import dataclass

# Canonical ordering of chord-alteration tokens. iRealPro preserves
# input order in its chord strings; music21 emits modifications in
# ChordStepModifications iteration order; neither is stable. The
# comparator's chord_symbol equality breaks if the SAME altered chord
# canonicalizes differently depending on which dialect wrote it
# (``C7b9#5`` vs ``C7#5b9``). We re-emit alterations in a fixed
# canonical order, ascending by degree with flat before sharp at the
# same degree — the jazz lead-sheet convention.
_ALTERATION_TOKEN_RE = re.compile(
    r"(?:b5|\#5|b6|\#6|b9|\#9|\#11|b13|alt|add9|add2)"
)
# Add-tones (add9, add2) sort after explicit alterations but before
# the umbrella ``alt``. Pulled out as a named constant per the third-
# pass review note — the magic number 90 obscured intent.
_ADD_TONE_RANK = 90
_ALT_UMBRELLA_RANK = 99
_ALTERATION_SORT_KEY: dict[str, tuple[int, int]] = {
    # (degree, accidental_rank — flat=0, sharp=1)
    "b5":   (5, 0),
    "#5":   (5, 1),
    "b6":   (6, 0),
    "#6":   (6, 1),
    "b9":   (9, 0),
    "#9":   (9, 1),
    "#11":  (11, 1),
    "b13":  (13, 0),
    "add9": (_ADD_TONE_RANK, 0),
    "add2": (_ADD_TONE_RANK, 1),
    "alt":  (_ALT_UMBRELLA_RANK, 0),  # umbrella "alt" sorts last
}


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


def canonical_alterations(alterations: str) -> str:
    """Re-emit a chord-alteration suffix in canonical jazz order.

    Conventional jazz lead-sheet order is ascending by degree, with
    flat before sharp at the same degree (``b5#5``, ``b9#9``,
    ``#11``, ``b13``, then ``add9`` / ``add2``, then the umbrella
    ``alt``). Unknown tokens stay at the end in input order so the
    comparator-relevant canonical doesn't silently drop them, but
    they're tracked separately so they sort after recognized tokens.

    The input alterations string is whatever the adapter accumulated;
    we extract recognized tokens, sort, and emit. Garbage between
    tokens (e.g. mismatched parens) is preserved verbatim at the end
    so adapter bugs don't get silently masked.
    """
    if not alterations:
        return ""
    recognized: list[str] = []
    pos = 0
    leftover: list[str] = []
    while pos < len(alterations):
        m = _ALTERATION_TOKEN_RE.match(alterations, pos)
        if m:
            recognized.append(m.group(0))
            pos = m.end()
        else:
            leftover.append(alterations[pos])
            pos += 1
    # ``alt`` is an umbrella ("any altered tone fits") and pairs
    # incoherently with explicit b9 / #9 / b5 / #5 alterations —
    # ``b9alt`` is semantically nonsense in lead-sheet convention.
    # Policy: when explicit alterations are present, drop the umbrella
    # ``alt`` (lossless — the explicit info is comparator-relevant and
    # would otherwise be hidden behind the umbrella). When ``alt``
    # appears alone, keep it.
    explicit_count = sum(1 for tok in recognized if tok != "alt")
    if explicit_count > 0:
        recognized = [tok for tok in recognized if tok != "alt"]
    recognized.sort(key=lambda tok: _ALTERATION_SORT_KEY.get(tok, (100, 0)))
    return "".join(recognized) + "".join(leftover)


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
    canon_alterations = canonical_alterations(alterations)
    canonical = canon_root + quality + canon_alterations
    return NormalizedChord(
        canonical=canonical,
        raw=raw or canonical,
        bass=canon_bass,
    )


__all__ = [
    "NormalizedChord",
    "canonical_alterations",
    "canonical_root",
    "canonicalize_chord_parts",
]
