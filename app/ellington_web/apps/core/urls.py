"""URL conf for apps.core — invite acceptance flow (epic #96 sub-ticket b / #108)."""

from __future__ import annotations

from django.urls import path

from . import views


app_name = "core"


urlpatterns = [
    path("invite/<str:token>/", views.accept_invite, name="accept_invite"),
]
