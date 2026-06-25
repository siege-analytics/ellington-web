"""CMS app — Wagtail-managed editorial content (#190 epic, #191 spike).

This app owns Wagtail ``Page`` subclasses for editorial content. Corpus
data (``apps.engine_rules``, ``apps.voicings``, ``apps.rule_review``,
``apps.charts``, ``apps.practice``) stays in its existing Django apps —
Wagtail owns prose, Django owns data. See #190 for the routing
decision (Wagtail catches ``/`` last; Django app paths win first).

``ready()`` wires up the role-sync signal handler from #196 so
``UserProfile.is_pedagogue`` toggles drive Wagtail Group membership.
"""

from django.apps import AppConfig


class CmsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.cms"
    verbose_name = "CMS"

    def ready(self) -> None:
        # Import here so the receiver registration happens after
        # Django's app registry is fully populated.
        from . import signals  # noqa: F401
