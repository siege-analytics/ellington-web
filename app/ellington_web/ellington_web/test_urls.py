"""Minimal URLconf for tests — main urls.py pulls in grappelli/locations/etc."""

from django.urls import include, path

urlpatterns = [
    # Mounted at the SAME prefix as the production urls.py for parity.
    path("critique/", include("apps.styles.urls")),
]
