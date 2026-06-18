from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Import signal handlers so they connect on app load.
        # Per epic #96 sub-ticket (j) / #131 — RolePromotionAudit
        # signal wiring on UserProfile field changes.
        from . import signals  # noqa: F401
