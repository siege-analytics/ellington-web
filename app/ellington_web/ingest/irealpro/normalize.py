"""Back-compat shim — the iRealPro normalizer now lives in ``charts_common``.

The original module moved here in #73 so the MuseScore (and future
Band-in-a-Box, OMR) adapters can share one canonical chord vocabulary.
The iRealPro parser + importer still import from
``ingest.irealpro.normalize`` — these re-exports keep that working
without a flag-day rename, and the symbols stay in this module's
``__all__`` so import-linters don't strip them.
"""

from __future__ import annotations

from ..charts_common.normalize import (
    NormalizedChord,
    canonical_root,
    canonicalize_chord_parts,
    normalize_chord_symbol,
    split_measure_chord_events,
)

__all__ = [
    "NormalizedChord",
    "canonical_root",
    "canonicalize_chord_parts",
    "normalize_chord_symbol",
    "split_measure_chord_events",
]
