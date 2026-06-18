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
    path(
        "recordings/<int:recording_pk>/share/",
        views.share_recording,
        name="share_recording",
    ),
    path("shared/", views.shared_with_me, name="shared_with_me"),
    path(
        "recordings/<int:recording_pk>/comments/add/",
        views.add_recording_comment,
        name="add_recording_comment",
    ),
    path(
        "comments/<int:comment_pk>/delete/",
        views.delete_recording_comment,
        name="delete_recording_comment",
    ),
    path(
        "comments/<int:comment_pk>/edit/",
        views.edit_recording_comment,
        name="edit_recording_comment",
    ),
    path("studios/", views.studio_list, name="studio_list"),
    path("studios/new/", views.studio_create, name="studio_create"),
    path("studios/<slug:slug>/", views.studio_detail, name="studio_detail"),
    path("studios/<slug:slug>/join/", views.studio_join, name="studio_join"),
    path("studios/<slug:slug>/leave/", views.studio_leave, name="studio_leave"),
]
