"""Data migration: seed a MasterProfilePage for Joe Pass (#198).

Creates a MastersIndexPage under the root, then a MasterProfilePage
linked to the Master with slug ``joe-pass``. The Master row itself
is seeded by the plugin catalog sync — if it doesn't exist yet, this
migration creates a placeholder so the page can link.

Idempotent: safe to re-run.
"""

from django.db import migrations
from django.utils.text import slugify


def seed_joe_pass_profile(apps, schema_editor):
    Master = apps.get_model("styles", "Master")
    Page = apps.get_model("wagtailcore", "Page")
    MastersIndexPage = apps.get_model("cms", "MastersIndexPage")
    MasterProfilePage = apps.get_model("cms", "MasterProfilePage")

    # Ensure a Joe Pass Master row exists. The plugin sync replaces
    # placeholder=True rows with real data once it runs; the page link
    # survives the upgrade.
    master, _ = Master.objects.get_or_create(
        slug="joe-pass",
        defaults={
            "name": "Joe Pass",
            "summary": "Solo jazz guitar chord-melody. Virtuosity in"
                       " self-accompaniment. Canon: Virtuoso, Chops, "
                       "I Remember Charlie Parker.",
            "is_placeholder": True,
            "extra": {},
        },
    )

    # Find or create the Masters index under the root page.
    root = Page.objects.filter(depth=1).first()
    if root is None:
        # No root page yet — Wagtail's initial migration usually creates
        # this. If missing, bail rather than fabricate a tree.
        return

    index = MastersIndexPage.objects.filter(slug="masters").first()
    if index is None:
        index = MastersIndexPage(
            title="Masters",
            slug="masters",
            intro="<p>Pedagogical biographies of the canonical players.</p>",
        )
        root.add_child(instance=index)

    if MasterProfilePage.objects.filter(slug="joe-pass").exists():
        return

    page = MasterProfilePage(
        title="Joe Pass",
        slug="joe-pass",
        master=master,
        intro="Solo jazz guitar's chord-melody benchmark.",
        body=[
            ("paragraph",
             "<p>Joe Pass (1929–1994) defined what a single guitarist "
             "could do alone with standards. His work with Oscar "
             "Peterson and Ella Fitzgerald rewards close listening; "
             "his solo records on Pablo (<em>Virtuoso</em>, "
             "<em>Chops</em>) are the source-of-truth for chord-melody "
             "voice-leading at this register.</p>"),
        ],
    )
    index.add_child(instance=page)


def remove_joe_pass_profile(apps, schema_editor):
    MasterProfilePage = apps.get_model("cms", "MasterProfilePage")
    MastersIndexPage = apps.get_model("cms", "MastersIndexPage")
    MasterProfilePage.objects.filter(slug="joe-pass").delete()
    MastersIndexPage.objects.filter(slug="masters").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0003_masters_index_and_profile"),
    ]

    operations = [
        migrations.RunPython(
            seed_joe_pass_profile,
            reverse_code=remove_joe_pass_profile,
        ),
    ]
