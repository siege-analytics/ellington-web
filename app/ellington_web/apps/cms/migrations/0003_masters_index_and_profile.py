"""Schema migration for MastersIndexPage + MasterProfilePage (#198).

Hand-written for parity with the rest of the cms app. The data
migration that seeds the Joe Pass page lives in
``0004_seed_joe_pass``.
"""

import django.db.models.deletion
import wagtail.blocks
import wagtail.fields
import wagtail.images.blocks
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0001_initial"),
        ("wagtailcore", "0001_initial"),
        ("wagtailimages", "0001_initial"),
        ("styles", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MastersIndexPage",
            fields=[
                ("page_ptr", models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to="wagtailcore.page")),
                ("intro", wagtail.fields.RichTextField(blank=True, help_text="Section intro for the Masters listing.")),
            ],
            options={
                "verbose_name": "Masters index",
            },
            bases=("wagtailcore.page",),
        ),
        migrations.CreateModel(
            name="MasterProfilePage",
            fields=[
                ("page_ptr", models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to="wagtailcore.page")),
                ("intro", models.CharField(blank=True, help_text="Above-the-fold lead line. Defaults to ``master.summary`` when empty.", max_length=512)),
                ("body", wagtail.fields.StreamField(
                    [
                        ("paragraph", wagtail.blocks.RichTextBlock(features=["h2", "h3", "h4", "bold", "italic", "ol", "ul", "link", "blockquote", "hr"])),
                        ("image", wagtail.images.blocks.ImageChooserBlock()),
                        ("quote", wagtail.blocks.BlockQuoteBlock()),
                    ],
                    blank=True,
                    help_text="Editorial prose. Block library is intentionally small for Phase 1 (#198); engine_rule_reference / voicing_reference blocks land in a follow-up.",
                    use_json_field=True,
                )),
                ("hero_image", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="wagtailimages.image", help_text="Hero image at the top of the page.")),
                ("master", models.ForeignKey(help_text="The corpus row this page is the editorial face of. PROTECT — page should not silently outlive its Master.", on_delete=django.db.models.deletion.PROTECT, related_name="profile_pages", to="styles.master")),
            ],
            options={
                "verbose_name": "Master profile page",
            },
            bases=("wagtailcore.page",),
        ),
    ]
