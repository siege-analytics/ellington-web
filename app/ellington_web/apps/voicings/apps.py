"""Voicings corpus app (epic #186 Phase 2).

Hosts the catalog of guitar chord voicings synced from the chord-
library plugin's ``plugin/data/voicings.json`` (locked schema at
``schema/voicings.schema.json`` in that repo, 820 voicings as of
plugin develop @ 2026-06-24). Consumed Phase 2b/3 by
``apps.rule_review`` to give the ``voicing_confirmed`` checkbox a
visual referent next to a fretboard render of the recommended voicing.
"""

from django.apps import AppConfig


class VoicingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.voicings"
    verbose_name = "Voicings"
