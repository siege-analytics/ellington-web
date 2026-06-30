"""URL config for the rule_review focus-group surface (epic #96 / #98).

Mounted at /rule-review/ in the project URLconf.
"""

from __future__ import annotations

from django.urls import path

from . import views


app_name = "rule_review"


urlpatterns = [
    path("", views.rule_list, name="rule_list"),
    path("library/", views.rule_library, name="rule_library"),
    path("rules/<int:pk>/", views.rule_detail, name="rule_detail"),
    path(
        "rules/<int:pk>/confirm/",
        views.confirm_rule,
        name="confirm_rule",
    ),
    path("queue/", views.admin_queue, name="admin_queue"),
    path(
        "confirmation-queue/",
        views.confirmation_queue,
        name="confirmation_queue",
    ),
    path("comments/add/", views.add_rule_comment, name="add_rule_comment"),
    path(
        "comments/<int:comment_pk>/delete/",
        views.delete_rule_comment,
        name="delete_rule_comment",
    ),
    path(
        "comments/<int:comment_pk>/edit/",
        views.edit_rule_comment,
        name="edit_rule_comment",
    ),
]
