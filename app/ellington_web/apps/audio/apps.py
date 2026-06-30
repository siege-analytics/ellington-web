"""Audio analysis pipeline app (epic #232).

Houses the deterministic-backing-reconstruction + per-beat verdict
pipeline pieces:

- ``SoundBank`` — discovered on the machine via
  ``scan_sound_banks``; used by the MuseScore backing-render task
- Future children of #232 land render task, alignment, pitch
  extraction, comparator, BeatCritique here

Pairs with ``apps.practice`` (existing Recording lifecycle + BackingTrack
container) and ``apps.engine_rules`` (firing-spec expectations to diff
against).
"""

from django.apps import AppConfig


class AudioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audio"
    verbose_name = "Audio"
