"""Cross-adapter parity: same chord via iRealPro vs music21 → same canonical.

This is the contract the comparator relies on. Phase 4-MS introduced
the music21 adapter; without this test, a regression in either
adapter (mismapping a quality, dropping an alteration, mis-handling a
flat/sharp) could silently break Style ↔ Master matching for any
chart imported via that format. The plugin-agent hostile review on
PR #74 flagged this gap explicitly.
"""

from __future__ import annotations

from django.test import SimpleTestCase
from music21 import harmony as m21_harmony

from ingest.irealpro.normalize import normalize_chord_symbol as irealpro_norm
from ingest.musescore.normalize import normalize_music21_chord_symbol


# (iRealPro_input, MuseScore_input, expected_canonical)
#
# Both columns describe the same chord in the source format's
# notation; both must canonicalize to the value in the third column.
# Comments in the source format on the right call out the dialect
# difference (iRealPro's ``-`` vs music21's ``m``, etc.).
PARITY_CHORDS: list[tuple[str, str, str]] = [
    ("C", "C", "C"),
    ("C-7", "Cm7", "Cm7"),
    ("D-7", "Dm7", "Dm7"),
    ("G7", "G7", "G7"),
    ("C^7", "Cmaj7", "Cmaj7"),
    ("Co7", "Co7", "Cdim7"),
    ("Ch7", "Cm7b5", "Cm7b5"),
    # Flat root: iRealPro uses ASCII 'b' (or Unicode ♭); music21
    # uses '-'. Both must land on 'Bb7'.
    ("Bb7", "B-7", "Bb7"),
    # Sharp root survives ASCII '#' on both sides.
    ("F#-7", "F#m7", "F#m7"),
]


class TestCrossAdapterParity(SimpleTestCase):
    """For every chord pair, both adapters produce the same canonical."""

    def test_iRealPro_vs_music21_canonical_parity(self) -> None:
        failures: list[str] = []
        for ireal_in, muse_in, expected in PARITY_CHORDS:
            ireal_out = irealpro_norm(ireal_in).canonical
            muse_out = normalize_music21_chord_symbol(
                m21_harmony.ChordSymbol(muse_in)
            ).canonical
            if ireal_out != expected:
                failures.append(
                    f"iRealPro({ireal_in!r}) → {ireal_out!r}, "
                    f"expected {expected!r}"
                )
            if muse_out != expected:
                failures.append(
                    f"music21({muse_in!r}) → {muse_out!r}, "
                    f"expected {expected!r}"
                )
            if ireal_out != muse_out:
                failures.append(
                    f"divergence on {expected!r}: "
                    f"iRealPro→{ireal_out!r}, music21→{muse_out!r}"
                )
        self.assertEqual(
            failures, [], "Cross-adapter canonical parity broken:\n  - "
            + "\n  - ".join(failures),
        )
