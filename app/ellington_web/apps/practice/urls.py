"""URL config for the practice-flow UI.

Mounted at ``/practice/`` in the main urlconf.
"""

from django.urls import path

from . import views

app_name = "practice"

urlpatterns = [
    path("sessions/", views.session_list, name="session_list"),
    path("sessions/new/", views.session_new, name="session_new"),
    path("sessions/<int:pk>/", views.session_detail, name="session_detail"),
    path("sessions/<int:pk>/delete/", views.session_delete, name="session_delete"),
    path(
        "recordings/<int:recording_pk>/reanalyze/",
        views.recording_reanalyze,
        name="recording_reanalyze",
    ),
]
