from django.urls import path

from . import views


app_name = "styles"

urlpatterns = [
    path("preview/", views.critique_preview, name="critique-preview"),
]
