"""Chord symbol normalization for iRealPro → canonical voicings.json vocabulary.

iRealPro uses compact notation that doesn't always match the plugin's
``masters.json`` ``chord_quality`` field. The comparator needs the
normalized form so its Style ↔ Master matching works. Raw form is
preserved for provenance.

Quality mapping (iRealPro → canonical):
    -       → m       (minor triad)
    -7      → m7      (minor 7)
    -^7     → m-maj7  (minor with major 7th — Greene/Laukens use this)
    -6      → m6
    ^       → maj     (major triad — rarely standalone, usually ^7)
    ^7      → maj7
    ^9      → maj9
    7       → 7
    7b9 etc → 7b9     (alterations preserved)
    o       → dim
    o7      → dim7
    h       → m7b5    (half-diminished; corpus uses 'min7b5')
    h7      → m7b5
    sus     → sus
    7sus    → 7sus
    +       → aug     (when standalone)
    7+      → 7#5     (some notations; pyRealParser may or may not normalize)
    +7      → 7#5

Slash chords (e.g. ``Cmaj7/G``): split into ``(chord, bass)``; canonical
stays on the chord-quality side, bass note kept separately so future
schemas can match on slash bass if needed.

The canonical vocabulary intentionally matches what the plugin's
``masters.json`` uses (e.g. ``maj7``, ``min7``, ``min7b5``, ``dom7``,
``dom7alt``, ``dom7b9``). The comparator's ``chord_quality`` matching
runs against this set; if iRealPro produces something we can't map, we
preserve the raw symbol and surface a warning so the corpus-coverage
gap is auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedChord:
    """Outcome of normalizing one iRealPro chord symbol.

    ``canonical`` is the form the comparator matches against (e.g.
    ``Cmaj7``, ``Bb7b9``, ``Am7b5``). ``raw`` is what iRealPro wrote
    verbatim (kept for debugging and for future re-normalization
    passes). ``bass`` is the slash-chord bass note when present, else
    ``None``.
    """

    canonical: str
    raw: str
    bass: str | None = None
    """For slash chords (e.g. ``Cmaj7/G``), the bass note (here ``G``).
    None when the chord has no slash bass. The canonical form does NOT
    include the bass — that lives here so the comparator can decide
    whether to ignore it (matching on quality only) or treat it as
    significant (e.g. for inversion-aware critique)."""

    warning: str | None = None
    """Non-empty when the normalizer couldn't fully canonicalize the
    raw symbol — e.g. an unknown extension, a malformed string. The
    canonical form is best-effort in those cases; callers should
    surface this to the import log so corpus-coverage gaps are visible.
    """


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
    # Dominant family — '7' is the default; extensions like '9', '11',
    # '13' are dominant when standalone after a root (e.g. 'C9' = C dom 9).
    # We treat bare digits as dominant extensions:
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

# After mapping the quality token, alterations follow (b5, #5, b9, #9, #11,
# b13, alt). iRealPro tends to keep these verbatim, so we preserve them.
# This regex captures the alteration tail after the quality token.
_ALTERATION_RE = re.compile(r"(?P<alt>(?:b5|\#5|b9|\#9|\#11|b13|alt|add\d+)+)")

# Root note regex: letter A-G, optional sharp/flat using either '#'/'b' or
# Unicode '♯'/'♭' (iRealPro may emit either). No '^' anchor — callers use
# .match() (which only matches at pos) for "starts here" checks and
# .search() for "find next root" scans.
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
            # Malformed slash bass — keep going but warn
            return NormalizedChord(
                canonical=raw,
                raw=raw,
                warning=f"unparseable slash bass {bass_part!r}",
            )

    # Strip pyRealPro-internal whitespace iRealPro sometimes embeds.
    chord_part = chord_part.replace(" ", "")

    # Extract root
    root_match = _ROOT_RE.match(chord_part)
    if not root_match:
        return NormalizedChord(
            canonical=raw,
            raw=raw,
            bass=bass,
            warning=f"unrecognized root in {raw!r}",
        )

    root = root_match.group("root")
    # Normalize Unicode sharp/flat to ASCII
    root = root.replace("♯", "#").replace("♭", "b")
    rest = chord_part[root_match.end():]

    # If nothing follows the root, it's a major triad
    if not rest:
        return NormalizedChord(canonical=root, raw=raw, bass=bass)

    # Try each quality token in order (longest first)
    quality_canon = None
    for ireal, canon in _QUALITY_MAP:
        if rest.startswith(ireal):
            quality_canon = canon
            rest = rest[len(ireal):]
            break

    if quality_canon is None:
        # No recognized quality token — unknown
        return NormalizedChord(
            canonical=root + rest,
            raw=raw,
            bass=bass,
            warning=f"unrecognized quality token after root in {raw!r}",
        )

    # Any remaining text should be alterations — preserved verbatim
    alterations = rest

    canonical = root + quality_canon + alterations
    return NormalizedChord(canonical=canonical, raw=raw, bass=bass)


def split_measure_chord_events(
    measure_string: str,
    beats_per_measure: int = 4,
) -> list[tuple[float, str]]:
    """Split a measure-string from pyRealParser into chord-event tuples.

    pyRealParser's ``measures_as_strings`` collapses multiple chords in
    one bar into a single string (e.g. ``'D-7G7'`` for a 4/4 measure
    with Dm7 on beat 1 and G7 on beat 3). This function recovers the
    individual chords + their beat positions.

    Convention for multi-chord bars (iRealPro standard):
        1 chord  → beat 1, lasts full measure
        2 chords → beats 1 and (beats_per_measure / 2 + 1) — typically 1 and 3
        3 chords → beats 1, 2.5, and (beats_per_measure / 2 + 1.5) — rare
        4 chords → beats 1, 2, 3, 4 in 4/4

    Returns a list of ``(beat, raw_chord_string)`` tuples. Caller is
    responsible for normalizing each raw chord via
    :func:`normalize_chord_symbol`.

    The raw_chord_string is what was extracted (e.g. ``'D-7'``,
    ``'G7'``) — not yet normalized.
    """
    s = measure_string.strip()
    if not s:
        return []

    # Split into chord-symbol tokens: each token starts with a root (A-G
    # optionally followed by # or b) and continues until the next root
    # or end of string. We use .search() with a starting position to find
    # subsequent root letters mid-string.
    tokens: list[str] = []
    # Find every position where a root letter begins. Need to anchor each
    # match independently because chord quality tokens contain letters
    # that overlap with root names (e.g. 'D-7G7' has 'G' as a root at
    # position 3, but we don't want to match the 'G' in a hypothetical
    # 'Dmaj' as a new root).
    # _ROOT_RE.finditer returns non-overlapping matches; a 'C#' chord
    # matches once at position 0 (the '#' is consumed by the optional
    # accidental group). So every match here is a potential chord start
    # — we just need to filter out slash-bass notes.
    root_positions: list[int] = []
    for match in _ROOT_RE.finditer(s):
        pos = match.start()
        # Skip if preceded by '/' — that's a slash-chord bass note glued
        # to the previous chord, not a new chord start (e.g. 'F/D' — the
        # 'D' is bass, not the next chord).
        if pos > 0 and s[pos - 1] == "/":
            continue
        root_positions.append(pos)

    if not root_positions:
        return []

    tokens = []
    for idx, start in enumerate(root_positions):
        end = root_positions[idx + 1] if idx + 1 < len(root_positions) else len(s)
        tokens.append(s[start:end])

    if not tokens:
        return []

    n = len(tokens)
    if n == 1:
        return [(1.0, tokens[0])]
    if n == 2:
        # Two chords: 1 and (half + 1) — in 4/4 → 1 and 3
        return [
            (1.0, tokens[0]),
            (float(beats_per_measure // 2 + 1), tokens[1]),
        ]
    if n == 4:
        return [(float(b + 1), t) for b, t in enumerate(tokens)]
    # 3 or other counts: distribute evenly across the bar
    step = beats_per_measure / n
    return [(1.0 + i * step, tokens[i]) for i in range(n)]


__all__ = ["NormalizedChord", "normalize_chord_symbol", "split_measure_chord_events"]
