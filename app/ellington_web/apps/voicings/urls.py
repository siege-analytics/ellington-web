"""URL config for apps.voicings (#186 Phase 2).

Mounted at /voicings/ in the project URLconf.
"""

from __future__ import annotations

from django.urls import path

from . import views


app_name = "voicings"


urlpatterns = [
    path("", views.voicing_list, name="voicing_list"),
    path("<int:pk>/", views.voicing_detail, name="voicing_detail"),
]
