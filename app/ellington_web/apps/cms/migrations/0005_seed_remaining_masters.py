"""Data migration: seed MasterProfilePage rows for the remaining
canonical masters — Kenny Burrell, George Van Eps, John McLaughlin
(#203, Phase 2 of #198).

Pattern is rote after Joe Pass (0004) proved the chain. Each entry:
- Ensures a placeholder Master row exists (real plugin sync replaces
  it when available)
- Creates a MasterProfilePage under the MastersIndexPage with a
  short editorial intro

Idempotent: existing rows / pages are preserved.
"""

from django.db import migrations


MASTERS = [
    {
        "slug": "kenny-burrell",
        "name": "Kenny Burrell",
        "summary": "Hard-bop-leaning all-rounder. Midnight Blue. Bluesy "
                   "phrasing married to clean octave-and-chord work.",
        "page_intro": "The bluesy backbone of jazz guitar lineage.",
        "page_body_html": (
            "<p>Kenny Burrell's voice on the guitar is the model for "
            "phrasing that swings without forcing — bluesy without "
            "becoming a blues player. <em>Midnight Blue</em> (Blue Note, "
            "1963) is the canonical statement; the Verve sides with "
            "Jimmy Smith are the next listen.</p>"
        ),
    },
    {
        "slug": "van-eps",
        "name": "George Van Eps",
        "summary": "Inventor of the 7-string guitar's modern role. "
                   "Pianistic chord-melody with independent bass lines.",
        "page_intro": "Solo guitar as a four-voice instrument.",
        "page_body_html": (
            "<p>Van Eps treated the guitar as a pianist's instrument: "
            "an independent walking bass line under a moving chord "
            "melody, all held in the right-hand fingers. His <em>"
            "Harmonic Mechanisms</em> volumes are the canonical study; "
            "the Concord trio records with Howard Alden are the "
            "best listen.</p>"
        ),
    },
    {
        "slug": "mclaughlin",
        "name": "John McLaughlin",
        "summary": "Cross-genre virtuoso. Mahavishnu Orchestra, "
                   "Shakti, acoustic Trio. Modal + rhythmic depth.",
        "page_intro": "Where modal jazz, Indian classical, and "
                       "fusion meet.",
        "page_body_html": (
            "<p>McLaughlin sits outside the chord-melody mainline but "
            "Ellington's framing of him as an all-time love is "
            "honest pedagogy: rhythmic vocabulary from Shakti, "
            "modal density from Mahavishnu, and the acoustic Trio's "
            "phrasing all repay close listening even if you never "
            "play in 13/8.</p>"
        ),
    },
]


def seed_remaining_masters(apps, schema_editor):
    Master = apps.get_model("styles", "Master")
    Page = apps.get_model("wagtailcore", "Page")
    MastersIndexPage = apps.get_model("cms", "MastersIndexPage")
    MasterProfilePage = apps.get_model("cms", "MasterProfilePage")

    index = MastersIndexPage.objects.filter(slug="masters").first()
    if index is None:
        # 0004 should have created it; if it didn't, bail rather than
        # invent a tree.
        return

    for spec in MASTERS:
        master, _ = Master.objects.get_or_create(
            slug=spec["slug"],
            defaults={
                "name": spec["name"],
                "summary": spec["summary"],
                "is_placeholder": True,
                "extra": {},
            },
        )
        if MasterProfilePage.objects.filter(slug=spec["slug"]).exists():
            continue

        page = MasterProfilePage(
            title=spec["name"],
            slug=spec["slug"],
            master=master,
            intro=spec["page_intro"],
            body=[("paragraph", spec["page_body_html"])],
        )
        index.add_child(instance=page)


def remove_remaining_masters(apps, schema_editor):
    MasterProfilePage = apps.get_model("cms", "MasterProfilePage")
    slugs = [m["slug"] for m in MASTERS]
    MasterProfilePage.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0004_seed_joe_pass"),
    ]

    operations = [
        migrations.RunPython(
            seed_remaining_masters,
            reverse_code=remove_remaining_masters,
        ),
    ]
