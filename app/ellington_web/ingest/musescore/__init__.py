"""MuseScore .mscz ingest — companion to ``ingest.irealpro``.

Phase 4-MS (#73) of epic #60. ``parser`` reads .mscz via
``music21``; ``normalize`` maps ``music21.harmony.ChordSymbol`` into
the shared canonical vocabulary in ``ingest.charts_common.normalize``;
``importer`` writes ``apps.charts`` rows under
``ImportSource.MUSESCORE``. Phase 4-PDF (#70) pipes omr-leadsheet's
.mscz output through this same path.
"""
