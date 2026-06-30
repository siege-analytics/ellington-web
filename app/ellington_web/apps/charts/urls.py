"""URL conf for the charts UI (Phase 4-PDF / #82)."""

from __future__ import annotations

from django.urls import path

from . import views


app_name = "charts"


urlpatterns = [
    path("upload-pdf/", views.upload_pdf_chart, name="upload_pdf"),
    path("imports/", views.chart_import_list, name="import_list"),
    path("imports/<int:pk>/", views.chart_import_detail, name="import_detail"),
    path(
        "imports/<int:pk>/reprocess/",
        views.chart_import_reprocess,
        name="import_reprocess",
    ),
    path("comments/add/", views.add_chart_comment, name="add_chart_comment"),
    path(
        "comments/<int:comment_pk>/delete/",
        views.delete_chart_comment,
        name="delete_chart_comment",
    ),
    path(
        "comments/<int:comment_pk>/edit/",
        views.edit_chart_comment,
        name="edit_chart_comment",
    ),
    path(
        "songs/<int:song_pk>/fires/",
        views.song_rule_fires,
        name="song_rule_fires",
    ),
    path("songbooks/", views.songbook_list, name="songbook_list"),
    path("songbooks/<int:pk>/share/", views.songbook_share, name="songbook_share"),
    path("songbooks/<int:pk>/visibility/", views.songbook_visibility, name="songbook_visibility"),
]
