"""Wagtail page models for ellington-web (#191 spike + #198 master profile).

- ``HomePage`` (/) — spike-grade, one rich-text intro field.
- ``MastersIndexPage`` (/masters/) — listing wrapper.
- ``MasterProfilePage`` (/masters/<slug>/) — first real content model.
  FK to ``apps.styles.Master`` so canonical biographical fields live
  in the Django corpus while editorial prose lives in StreamField.

Per #190: Wagtail owns prose; Django owns data. The FK to Master
prevents drift — the page renders ``master.name`` and ``master.summary``
straight from the corpus, never duplicated.
"""

from __future__ import annotations

from django.db import models
from wagtail import blocks
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField, StreamField
from wagtail.images.blocks import ImageChooserBlock
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


class MastersIndexPage(Page):
    """Wrapper page at ``/masters/`` listing all MasterProfilePages.

    Phase 1 just renders the title + introduction + a list of children.
    Future enrichment (filter by era, instrument, region) is deferred.
    """

    intro = RichTextField(
        blank=True,
        help_text="Section intro for the Masters listing.",
    )

    content_panels = Page.content_panels + [
        FieldPanel("intro"),
    ]

    subpage_types = ["cms.MasterProfilePage"]

    class Meta:
        verbose_name = "Masters index"


class MasterProfilePage(Page):
    """One page per Master (Joe Pass, Burrell, Van Eps, …).

    Canonical biographical fields read straight from
    ``apps.styles.Master`` via the FK — page renders ``master.name``
    and ``master.summary`` without duplication. Editorial prose
    (anecdotes, recommended journeys, anchor quotes) lives in
    ``body``.
    """

    master = models.ForeignKey(
        "styles.Master",
        on_delete=models.PROTECT,
        related_name="profile_pages",
        help_text="The corpus row this page is the editorial face of."
        " PROTECT — page should not silently outlive its Master.",
    )
    intro = models.CharField(
        max_length=512,
        blank=True,
        help_text="Above-the-fold lead line. Defaults to ``master.summary``"
        " when empty.",
    )
    body = StreamField(
        [
            ("paragraph", blocks.RichTextBlock(features=[
                "h2", "h3", "h4", "bold", "italic", "ol", "ul", "link",
                "blockquote", "hr",
            ])),
            ("image", ImageChooserBlock()),
            ("quote", blocks.BlockQuoteBlock()),
        ],
        blank=True,
        use_json_field=True,
        help_text="Editorial prose. Block library is intentionally small"
        " for Phase 1 (#198); engine_rule_reference / voicing_reference"
        " blocks land in a follow-up.",
    )
    hero_image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Hero image at the top of the page.",
    )

    content_panels = Page.content_panels + [
        FieldPanel("master"),
        FieldPanel("hero_image"),
        FieldPanel("intro"),
        FieldPanel("body"),
    ]

    parent_page_types = ["cms.MastersIndexPage"]

    class Meta:
        verbose_name = "Master profile page"
