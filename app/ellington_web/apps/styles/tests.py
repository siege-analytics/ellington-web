"""Model-layer tests for apps.styles.

Covers: slug uniqueness across the three catalogs, StylePreset's
at-least-one-axis invariant, StyleSelection's PROTECT on preset
deletion, Critique cascade on selection deletion, and the
``axis_summary`` helper used by admin.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.styles.models import (
    Critique,
    Idiom,
    Master,
    Style,
    StylePreset,
    StyleSelection,
)


User = get_user_model()


class CatalogSlugUniquenessTests(TestCase):
    def test_master_slug_unique(self):
        Master.objects.create(slug="joe-pass", name="Joe Pass")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Master.objects.create(slug="joe-pass", name="duplicate")

    def test_style_slug_unique(self):
        Style.objects.create(slug="bebop", name="Bebop")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Style.objects.create(slug="bebop", name="duplicate")

    def test_idiom_slug_unique(self):
        Idiom.objects.create(slug="comping", name="Comping")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Idiom.objects.create(slug="comping", name="duplicate")

    def test_catalog_rows_default_to_placeholder(self):
        m = Master.objects.create(slug="van-eps", name="Van Eps")
        s = Style.objects.create(slug="cool-jazz", name="Cool Jazz")
        i = Idiom.objects.create(slug="chord-melody", name="Chord Melody")
        self.assertTrue(m.is_placeholder)
        self.assertTrue(s.is_placeholder)
        self.assertTrue(i.is_placeholder)
        # schema_version defaults
        self.assertEqual(m.schema_version, "v1")
        self.assertEqual(s.schema_version, "v1")
        self.assertEqual(i.schema_version, "v1")


class StylePresetAxisTests(TestCase):
    def setUp(self):
        self.master = Master.objects.create(slug="joe-pass", name="Joe Pass")
        self.style = Style.objects.create(slug="bebop", name="Bebop")
        self.idiom = Idiom.objects.create(slug="comping", name="Comping")

    def test_all_three_axes_valid(self):
        preset = StylePreset(
            slug="joe-pass-bebop-comping",
            display_name="Joe Pass × Bebop × Comping",
            master=self.master,
            style=self.style,
            idiom=self.idiom,
        )
        preset.full_clean()  # should not raise
        preset.save()
        self.assertEqual(preset.axis_summary, "master=joe-pass × style=bebop × idiom=comping")

    def test_master_only_valid(self):
        preset = StylePreset(
            slug="joe-pass",
            display_name="Joe Pass",
            master=self.master,
        )
        preset.full_clean()
        preset.save()
        self.assertEqual(preset.axis_summary, "master=joe-pass")

    def test_style_only_valid(self):
        preset = StylePreset(slug="bebop", display_name="Bebop", style=self.style)
        preset.full_clean()
        preset.save()

    def test_idiom_only_valid(self):
        preset = StylePreset(slug="comping", display_name="Comping", idiom=self.idiom)
        preset.full_clean()
        preset.save()

    def test_no_axes_raises_validation_error(self):
        preset = StylePreset(slug="empty", display_name="Empty")
        with self.assertRaises(ValidationError) as ctx:
            preset.full_clean()
        self.assertIn("master", str(ctx.exception))
        self.assertIn("style", str(ctx.exception))
        self.assertIn("idiom", str(ctx.exception))

    def test_axis_summary_empty_when_no_axes(self):
        # The model accepts an unclean save (clean() is opt-in); axis_summary
        # should degrade gracefully rather than crash.
        preset = StylePreset.objects.create(slug="bypass-clean", display_name="Bypass")
        self.assertEqual(preset.axis_summary, "(no axes)")


class StyleSelectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="dheeraj")
        self.style = Style.objects.create(slug="bebop", name="Bebop")
        self.backing_style = Style.objects.create(slug="bossa-nova", name="Bossa Nova")
        self.target = StylePreset.objects.create(slug="t", display_name="t", style=self.style)
        self.backing = StylePreset.objects.create(
            slug="b", display_name="b", style=self.backing_style,
        )

    def test_can_create_selection(self):
        sel = StyleSelection.objects.create(
            user=self.user, target_preset=self.target, backing_preset=self.backing,
        )
        self.assertIsNotNone(sel.started_at)

    def test_preset_deletion_is_protected(self):
        StyleSelection.objects.create(
            user=self.user, target_preset=self.target, backing_preset=self.backing,
        )
        from django.db.models.deletion import ProtectedError
        with self.assertRaises(ProtectedError):
            self.target.delete()

    def test_critique_cascades_with_selection(self):
        sel = StyleSelection.objects.create(
            user=self.user, target_preset=self.target, backing_preset=self.backing,
        )
        Critique.objects.create(selection=sel, style_match_score=0.75, detected_axes={})
        Critique.objects.create(selection=sel, style_match_score=0.80, detected_axes={})
        self.assertEqual(sel.critiques.count(), 2)
        sel.delete()
        self.assertEqual(Critique.objects.count(), 0)


class CritiqueShapeTests(TestCase):
    def setUp(self):
        user = User.objects.create(username="dheeraj")
        style = Style.objects.create(slug="bebop", name="Bebop")
        backing = Style.objects.create(slug="bossa-nova", name="Bossa Nova")
        target = StylePreset.objects.create(slug="t", display_name="t", style=style)
        bk = StylePreset.objects.create(slug="b", display_name="b", style=backing)
        self.sel = StyleSelection.objects.create(
            user=user, target_preset=target, backing_preset=bk,
        )

    def test_critique_carries_structured_detected_axes(self):
        c = Critique.objects.create(
            selection=self.sel,
            style_match_score=0.42,
            detected_axes={
                "style": {"slug": "cool-jazz", "confidence": 0.61},
                "idiom": {"slug": "chord-melody", "confidence": 0.74},
            },
            commentary="The user selected bebop but the comparator detected cool-jazz tendencies.",
            audio_input_ref="audio:demo-passage:1",
        )
        c.refresh_from_db()
        self.assertEqual(c.detected_axes["style"]["slug"], "cool-jazz")
        self.assertAlmostEqual(c.detected_axes["idiom"]["confidence"], 0.74)
