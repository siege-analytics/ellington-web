"""Shared ingest utilities used by every chart-format adapter.

Each adapter (``irealpro``, ``musescore``, future ``biab`` / ``pdf``) maps
its source format into the same ``NormalizedChord`` vocabulary defined
here, so the chord comparator and the timeline see one canonical chord
representation regardless of where the chart came from.
"""
