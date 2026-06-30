"""Wagtail page models for ellington-web (#191 spike).

Spike scope: prove Wagtail can install + coexist with the Django
apps without touching corpus data. Ships ONE trivial Page subclass
(``HomePage``) at ``/``. Full page-model catalog lands as a separate
child of #190.
"""

from __future__ import annotations

from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Page


class HomePage(Page):
    """The site home page at ``/``.

    Spike-grade: a heading + one rich-text intro field. Future
    children of #190 will replace this with a real StreamField-driven
    landing page.
    """

    intro = RichTextField(
        blank=True,
        help_text="Brief site introduction. Rendered on the home page.",
    )

    content_panels = Page.content_panels + [
        FieldPanel("intro"),
    ]

    class Meta:
        verbose_name = "Home page"
