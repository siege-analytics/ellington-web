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
]
