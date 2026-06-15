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


# (iRealPro_input, MuseScore_input, expected_canonical, expected_bass)
#
# Both source columns describe the same chord; both must canonicalize
# to the same (canonical, bass) pair. ``expected_bass`` is None for
# non-slash chords. Comments inline call out where the source dialects
# diverge (iRealPro's ``-`` vs music21's ``m``, iRealPro's ``^`` vs
# music21's ``maj``, music21's flat spelling ``-`` vs iRealPro's
# ``b``, etc.).
#
# Coverage matrix (post #74 second-pass review — slash + alteration
# rows added because that's where #76 says the alteration token is
# fragile, and where a regression would otherwise sneak in unseen):
#   - basic qualities (major, minor7, dom7, maj7, dim7, half-dim7)
#   - flat root (Bb7 ↔ B-7)
#   - sharp root (F#m7 ↔ F#m7)
#   - dom7 alterations (b9, #9, b5, #5)
#   - multi-alteration ordering stability (7b9b5)
#   - slash chord with bass note preservation (C/G, Bb7/F)
PARITY_CHORDS: list[tuple[str, str, str, str | None]] = [
    # Basics
    ("C", "C", "C", None),
    ("C-7", "Cm7", "Cm7", None),
    ("D-7", "Dm7", "Dm7", None),
    ("G7", "G7", "G7", None),
    ("C^7", "Cmaj7", "Cmaj7", None),
    ("Co7", "Co7", "Cdim7", None),
    ("Ch7", "Cm7b5", "Cm7b5", None),
    # Accidentals on the root
    ("Bb7", "B-7", "Bb7", None),
    ("F#-7", "F#m7", "F#m7", None),
    # Dominant alterations — same codepath as #76 (alteration-token
    # semitone math). The parity test pins behavior so a refactor of
    # _alteration_token can't silently regress.
    ("C7b9", "C7b9", "C7b9", None),
    ("C7#9", "C7#9", "C7#9", None),
    ("C7b5", "C7b5", "C7b5", None),
    ("C7#5", "C7#5", "C7#5", None),
    # Multi-alteration ordering stability: canonical_alterations()
    # re-emits in fixed jazz-lead-sheet order (ascending degree, then
    # flat before sharp at the same degree). The same chord written
    # with alterations in different input order must produce the
    # SAME canonical regardless — that's the contract the comparator
    # depends on, and the regression risk #76's refactor would hit
    # if the parity test doesn't pin it.
    ("C7b9b5", "C7b9b5", "C7b5b9", None),  # input order: b9 then b5
    ("C7b5b9", "C7b5b9", "C7b5b9", None),  # input order: b5 then b9 — same canonical
    ("C7b9#5", "C7b9#5", "C7#5b9", None),  # b9 + #5 normalize to #5 first (degree 5 first)
    ("C7#5b9", "C7#5b9", "C7#5b9", None),  # already-canonical input — stays put
    # Alt umbrella + explicit alteration interaction (third-pass review).
    # Policy: when explicit alterations are present, ``alt`` is dropped
    # (lossless preservation of comparator-relevant info). Bare ``alt``
    # — no explicit accompaniment — is preserved as the umbrella.
    # iRealPro writes both forms; music21 accepts ``alt`` via the
    # ``alter`` modifier but the comparator-side canonical is what we
    # pin here.
    ("C7altb9", "C7b9", "C7b9", None),
    # min-maj7 family: iRealPro writes -^7, music21 understands mM7
    # (m-maj7 specifically rejects in 9.x parser). The canonical
    # ``m-maj7`` is where both adapters meet. This is the family
    # where the parsers most often diverge in the wild — pinning it.
    ("C-^7", "CmM7", "Cm-maj7", None),
    # Slash chords — bass preserved separately from the canonical.
    ("C/G", "C/G", "C", "G"),
    ("Bb7/F", "B-7/F", "Bb7", "F"),
]


class TestCrossAdapterParity(SimpleTestCase):
    """For every chord pair, both adapters produce the same canonical AND bass."""

    def test_iRealPro_vs_music21_canonical_parity(self) -> None:
        failures: list[str] = []
        for ireal_in, muse_in, expected_canonical, expected_bass in PARITY_CHORDS:
            ireal_out = irealpro_norm(ireal_in)
            muse_out = normalize_music21_chord_symbol(
                m21_harmony.ChordSymbol(muse_in)
            )
            # Canonical chord_symbol must match the expected and each other
            if ireal_out.canonical != expected_canonical:
                failures.append(
                    f"iRealPro({ireal_in!r}) canonical={ireal_out.canonical!r}, "
                    f"expected {expected_canonical!r}"
                )
            if muse_out.canonical != expected_canonical:
                failures.append(
                    f"music21({muse_in!r}) canonical={muse_out.canonical!r}, "
                    f"expected {expected_canonical!r}"
                )
            if ireal_out.canonical != muse_out.canonical:
                failures.append(
                    f"canonical divergence on {expected_canonical!r}: "
                    f"iRealPro→{ireal_out.canonical!r}, "
                    f"music21→{muse_out.canonical!r}"
                )
            # Slash-chord bass must match too — comparator-relevant
            # for inversion-aware critique, and the place the original
            # iRealPro path silently dropped the bass on malformed
            # input before we tightened slash-bass parsing.
            if ireal_out.bass != expected_bass:
                failures.append(
                    f"iRealPro({ireal_in!r}) bass={ireal_out.bass!r}, "
                    f"expected {expected_bass!r}"
                )
            if muse_out.bass != expected_bass:
                failures.append(
                    f"music21({muse_in!r}) bass={muse_out.bass!r}, "
                    f"expected {expected_bass!r}"
                )
            if ireal_out.bass != muse_out.bass:
                failures.append(
                    f"bass divergence on {expected_canonical!r}: "
                    f"iRealPro→{ireal_out.bass!r}, "
                    f"music21→{muse_out.bass!r}"
                )
        self.assertEqual(
            failures,
            [],
            "Cross-adapter parity broken:\n  - " + "\n  - ".join(failures),
        )
