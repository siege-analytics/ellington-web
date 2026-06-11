from django.apps import AppConfig


class ChartsConfig(AppConfig):
    name = "apps.charts"
    label = "charts"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Charts (songbooks, songs, chord events)"
