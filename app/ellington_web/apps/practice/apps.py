from django.apps import AppConfig


class PracticeConfig(AppConfig):
    name = "apps.practice"
    label = "practice"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Practice (sessions, backing tracks, recordings, stems)"
