"""Add engine_rule_reference block to MasterProfilePage.body (#200).

Hand-written for parity with the rest of the cms migrations.
StreamField block additions are non-destructive — existing pages
keep their stored block list; the new block type is just available
for future edits.
"""

import wagtail.blocks
import wagtail.fields
import wagtail.images.blocks
from django.db import migrations

from apps.cms.blocks import EngineRuleReferenceBlock


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0004_seed_joe_pass"),
    ]

    operations = [
        migrations.AlterField(
            model_name="masterprofilepage",
            name="body",
            field=wagtail.fields.StreamField(
                [
                    ("paragraph", wagtail.blocks.RichTextBlock(features=["h2", "h3", "h4", "bold", "italic", "ol", "ul", "link", "blockquote", "hr"])),
                    ("image", wagtail.images.blocks.ImageChooserBlock()),
                    ("quote", wagtail.blocks.BlockQuoteBlock()),
                    ("engine_rule_reference", EngineRuleReferenceBlock()),
                ],
                blank=True,
                help_text="Editorial prose. Block library is intentionally small for Phase 1 (#198); engine_rule_reference / voicing_reference blocks land in a follow-up.",
                use_json_field=True,
            ),
        ),
    ]
