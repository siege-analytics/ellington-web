"""iRealPro-dialect chord-symbol parsing → canonical ``NormalizedChord``.

iRealPro uses compact notation (``-`` for minor, ``^`` for major-7,
``h`` for half-diminished, ``o`` for diminished, Unicode ``♭`` / ``♯``
for accidentals) that doesn't match the canonical vocabulary the
comparator runs against. This module owns the iRealPro-specific
mapping; the canonical end of the pipeline
(:class:`NormalizedChord`, :func:`canonicalize_chord_parts`) lives in
``ingest.charts_common.normalize`` and is shared with every other
adapter (MuseScore, BiaB, OMR).

The split was made in PR #74 after the hostile review flagged that
the lifted ``charts_common.normalize`` module was carrying iRealPro's
quality table, multi-chord measure splitter, and Unicode-flat root
regex — none of which any other adapter wants. Keeping the
format-specific code here keeps ``charts_common`` honest.
"""

from __future__ import annotations

import re

from ..charts_common.normalize import NormalizedChord, canonical_alterations

# iRealPro quality token → canonical quality token.
# Order matters: longer keys must be tried before shorter prefixes
# (e.g. ``-^7`` before ``-7`` before ``-``).
_QUALITY_MAP: list[tuple[str, str]] = [
    # Minor / minor-major family
    ("-^7", "m-maj7"),
    ("-^9", "m-maj9"),
    ("-6", "m6"),
    ("-69", "m69"),
    ("-9", "m9"),
    ("-11", "m11"),
    ("-13", "m13"),
    ("-7", "m7"),
    ("-", "m"),
    # Half-diminished (iRealPro uses 'h' or 'h7' for half-dim)
    ("h7", "m7b5"),
    ("h9", "m9b5"),
    ("h", "m7b5"),
    # Diminished
    ("o7", "dim7"),
    ("o", "dim"),
    # Augmented (when written as '+')
    ("+7", "7#5"),
    ("+", "aug"),
    # Major-7 family (iRealPro uses '^' for maj7)
    ("^7", "maj7"),
    ("^9", "maj9"),
    ("^13", "maj13"),
    ("^", "maj"),
    # Suspended
    ("7sus", "7sus"),
    ("sus", "sus"),
    # Dominant family — '7' is the default; bare digits after the root
    # (``C9``, ``C11``, ``C13``) are dominant extensions.
    ("13", "13"),
    ("11", "11"),
    ("9", "9"),
    ("7", "7"),
    # Major-6 and 6/9 family (very common in jazz lead sheets)
    ("69", "6/9"),
    ("6", "6"),
    # Power chord and add-variants (uncommon in jazz but appear)
    ("add9", "add9"),
    ("add2", "add2"),
    ("5", "5"),
    # No-third / no-fifth markers (iRealPro pedal/drone notation; rare)
    ("2", "sus2"),
]

# Root note regex: letter A-G, optional sharp/flat using either '#'/'b'
# or Unicode '♯'/'♭' (iRealPro may emit either). No '^' anchor —
# callers use ``.match()`` for "starts here" and ``.finditer()`` for
# "find next root" scans.
_ROOT_RE = re.compile(r"(?P<root>[A-G][#b♯♭]?)")


def normalize_chord_symbol(raw: str) -> NormalizedChord:
    """Normalize one iRealPro chord token to canonical form.

    Returns ``NormalizedChord(canonical=raw, warning=...)`` when the
    input is unparseable — callers should surface ``warning`` to the
    import log but not fail the import. The canonical form for an
    unrecognized symbol is the raw input; downstream consumers can
    still display it even if the comparator can't match on it.
    """
    raw = (raw or "").strip()
    if not raw:
        return NormalizedChord(canonical="", raw="", warning="empty chord symbol")

    # Slash chord — split bass first; everything before '/' is the chord proper.
    chord_part = raw
    bass = None
    if "/" in raw:
        chord_part, _, bass_part = raw.partition("/")
        bass_part = bass_part.strip()
        # Use fullmatch so trailing garbage (e.g. ``Cmaj7/Gfoo``) is
        # rejected rather than silently accepted as bass='G'. The bass
        # token must be a complete root + optional accidental, nothing
        # more.
        if bass_part and _ROOT_RE.fullmatch(bass_part):
            bass = bass_part
        else:
            return NormalizedChord(
                canonical=raw,
                raw=raw,
                warning=f"unparseable slash bass {bass_part!r}",
            )

    # Strip pyRealParser-internal whitespace iRealPro sometimes embeds.
    chord_part = chord_part.replace(" ", "")

    root_match = _ROOT_RE.match(chord_part)
    if not root_match:
        return NormalizedChord(
            canonical=raw,
            raw=raw,
            bass=bass,
            warning=f"unrecognized root in {raw!r}",
        )

    root = root_match.group("root")
    # ASCII-normalize Unicode sharp/flat — keeps the canonical form
    # consistent with the music21 adapter's output.
    root = root.replace("♯", "#").replace("♭", "b")
    rest = chord_part[root_match.end():]

    if not rest:
        return NormalizedChord(canonical=root, raw=raw, bass=bass)

    quality_canon = None
    for ireal, canon in _QUALITY_MAP:
        if rest.startswith(ireal):
            quality_canon = canon
            rest = rest[len(ireal):]
            break

    if quality_canon is None:
        return NormalizedChord(
            canonical=root + rest,
            raw=raw,
            bass=bass,
            warning=f"unrecognized quality token after root in {raw!r}",
        )

    # Route alterations through the shared canonicalizer so multi-alt
    # chords have a stable ordering regardless of how iRealPro wrote
    # them (e.g. ``b9#5`` and ``#5b9`` both → ``b9#5``).
    alterations = canonical_alterations(rest)
    canonical = root + quality_canon + alterations
    return NormalizedChord(canonical=canonical, raw=raw, bass=bass)


def split_measure_chord_events(
    measure_string: str,
    beats_per_measure: int = 4,
) -> list[tuple[float, str]]:
    """Split a pyRealParser measure-string into ``(beat, chord)`` tuples.

    pyRealParser's ``measures_as_strings`` collapses multiple chords in
    one bar into a single string (e.g. ``'D-7G7'`` for a 4/4 measure
    with Dm7 on beat 1 and G7 on beat 3). This recovers the individual
    chords + their beat positions.

    Convention for multi-chord bars (iRealPro standard):
        1 chord  → beat 1, lasts full measure
        2 chords → beats 1 and (beats_per_measure / 2 + 1) — typically 1 and 3
        3 chords → distributed evenly
        4 chords → beats 1, 2, 3, 4 in 4/4

    Caller is responsible for normalizing each raw chord via
    :func:`normalize_chord_symbol`.
    """
    s = measure_string.strip()
    if not s:
        return []

    # Find every position where a root letter begins. Slash-chord bass
    # notes glued to the previous chord (e.g. 'F/D' — the 'D' is bass,
    # not the next chord) are filtered out.
    root_positions: list[int] = []
    for match in _ROOT_RE.finditer(s):
        pos = match.start()
        if pos > 0 and s[pos - 1] == "/":
            continue
        root_positions.append(pos)

    if not root_positions:
        return []

    tokens: list[str] = []
    for idx, start in enumerate(root_positions):
        end = root_positions[idx + 1] if idx + 1 < len(root_positions) else len(s)
        tokens.append(s[start:end])

    n = len(tokens)
    if n == 1:
        return [(1.0, tokens[0])]
    if n == 2:
        return [
            (1.0, tokens[0]),
            (float(beats_per_measure // 2 + 1), tokens[1]),
        ]
    if n == 4:
        return [(float(b + 1), t) for b, t in enumerate(tokens)]
    step = beats_per_measure / n
    return [(1.0 + i * step, tokens[i]) for i in range(n)]


__all__ = [
    "NormalizedChord",  # re-exported so existing importers keep working
    "normalize_chord_symbol",
    "split_measure_chord_events",
]
