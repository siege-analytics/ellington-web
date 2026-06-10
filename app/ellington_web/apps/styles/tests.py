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
"""Comparator + style-distance tests.

Covers: symmetry of shared/diverging tags, characteristic_quote
extraction (asymmetric), signature alignment verdicts, end-to-end
critique against a hard-coded passage including the bossa/gypsy/bebop
triangle from the product brief.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.styles.comparator import (
    DetectedVoicing,
    critique_passage,
    persist_critique,
    style_distance,
)
from apps.styles.models import (
    Critique,
    Style,
    StylePreset,
    StyleSelection,
)


User = get_user_model()


def _make_style(slug, *, tags=None, rhythmic=None, harmonic=None, notes=None, placeholder=True):
    return Style.objects.create(
        slug=slug,
        name=slug.title(),
        voicing_style_tag_affinity={t: 1.0 for t in (tags or [])},
        rhythmic_signature=rhythmic or {},
        harmonic_signature=harmonic or {},
        divergence_notes=notes or [],
        is_placeholder=placeholder,
    )


class StyleDistanceTests(TestCase):
    def test_shared_and_diverging_tags(self):
        bebop = _make_style("bebop", tags=["chromatic", "shell", "walking"])
        bossa = _make_style("bossa-nova", tags=["chromatic", "anticipated-bass"])
        dist = style_distance(bebop, bossa)
        self.assertEqual(dist.shared_tags, frozenset({"chromatic"}))
        # symmetric difference — order-independent
        self.assertEqual(
            dist.diverging_tags,
            frozenset({"shell", "walking", "anticipated-bass"}),
        )

    def test_distance_is_symmetric_in_tags(self):
        bebop = _make_style("bebop", tags=["a", "b"])
        bossa = _make_style("bossa", tags=["b", "c"])
        ab = style_distance(bebop, bossa)
        ba = style_distance(bossa, bebop)
        self.assertEqual(ab.shared_tags, ba.shared_tags)
        self.assertEqual(ab.diverging_tags, ba.diverging_tags)

    def test_characteristic_quote_is_asymmetric(self):
        bebop = _make_style(
            "bebop",
            tags=["shell"],
            notes=[
                {
                    "vs_style": "bossa-nova",
                    "shared_dimensions": ["chromatic"],
                    "diverging_dimensions": ["onset_anticipation"],
                    "characteristic_quote": "you're using bebop chords in bossa nova rhythm",
                },
            ],
        )
        bossa = _make_style("bossa-nova", tags=["shell"])
        # When the target is bossa and the user played bebop, the quote
        # comes from BEBOP against BOSSA.
        d_a_to_b = style_distance(bossa, bebop)
        self.assertEqual(
            d_a_to_b.characteristic_quote_from_b,
            "you're using bebop chords in bossa nova rhythm",
        )
        # The reverse direction has no authored quote — None.
        d_b_to_a = style_distance(bebop, bossa)
        self.assertIsNone(d_b_to_a.characteristic_quote_from_b)

    def test_signature_alignment_verdicts(self):
        a = _make_style(
            "a",
            rhythmic={"onset_anticipation": "anticipated", "density": "medium"},
            harmonic={"chromatic_motion_tolerance": "high"},
        )
        b = _make_style(
            "b",
            rhythmic={"onset_anticipation": "anticipated", "density": "dense"},
            harmonic={},  # unknown
        )
        dist = style_distance(a, b)
        self.assertEqual(dist.signature_alignment["onset_anticipation"], "aligned")
        self.assertEqual(dist.signature_alignment["density"], "divergent")
        self.assertEqual(dist.signature_alignment["chromatic_motion_tolerance"], "unknown")

    def test_placeholder_flag_propagates(self):
        a = _make_style("a", placeholder=True)
        b = _make_style("b", placeholder=False)
        dist = style_distance(a, b)
        self.assertTrue(dist.placeholder_flag)


class CritiquePassageTests(TestCase):
    """End-to-end critique covering the bossa/gypsy/bebop product example."""

    def setUp(self):
        self.user = User.objects.create(username="dheeraj")

        # Three styles. Bossa is what the user SAID, gypsy is the backing,
        # bebop is what they're ACTUALLY playing.
        self.bossa = _make_style(
            "bossa-nova",
            tags=["anticipated-bass", "chromatic"],
            rhythmic={"onset_anticipation": "anticipated"},
        )
        self.gypsy = _make_style(
            "gypsy-jazz",
            tags=["arpeggio", "string-sweep"],
        )
        self.bebop = _make_style(
            "bebop",
            tags=["chromatic", "shell", "walking"],
            rhythmic={"onset_anticipation": "anticipated"},
            notes=[
                {
                    "vs_style": "bossa-nova",
                    "characteristic_quote": "you're using bebop chords in bossa nova rhythm",
                },
            ],
        )
        self.ralph_patt_style = _make_style(
            "chromatic-cool",
            tags=["chromatic", "cluster"],
        )

        self.target_preset = StylePreset.objects.create(
            slug="t-bossa", display_name="Bossa target", style=self.bossa,
        )
        self.backing_preset = StylePreset.objects.create(
            slug="b-gypsy", display_name="Gypsy backing", style=self.gypsy,
        )
        self.selection = StyleSelection.objects.create(
            user=self.user,
            target_preset=self.target_preset,
            backing_preset=self.backing_preset,
        )

    def test_critique_emits_match_score_against_target(self):
        passage = [
            DetectedVoicing(chord_symbol="Cmaj7", voicing_style_tags=("chromatic", "shell")),
            DetectedVoicing(chord_symbol="Am7", voicing_style_tags=("chromatic", "walking")),
        ]
        draft = critique_passage(passage, self.selection, candidate_styles=[
            self.bossa, self.bebop, self.gypsy, self.ralph_patt_style,
        ])
        # Passage intersects bossa on 'chromatic' (1 shared); union is 4 →
        # 0.25 match score.
        self.assertAlmostEqual(draft.style_match_score, 0.25, places=3)

    def test_critique_detects_divergent_style(self):
        passage = [
            DetectedVoicing(chord_symbol="Cmaj7", voicing_style_tags=("chromatic", "shell", "walking")),
        ]
        draft = critique_passage(passage, self.selection, candidate_styles=[
            self.bossa, self.bebop, self.gypsy, self.ralph_patt_style,
        ])
        # bebop has all three tags from passage; bossa has only 'chromatic'.
        # bebop should be the detected style.
        self.assertEqual(draft.detected_axes["style"]["slug"], "bebop")

    def test_critique_renders_characteristic_quote(self):
        passage = [
            DetectedVoicing(chord_symbol="Cmaj7", voicing_style_tags=("chromatic", "shell", "walking")),
        ]
        draft = critique_passage(passage, self.selection, candidate_styles=[
            self.bossa, self.bebop, self.gypsy, self.ralph_patt_style,
        ])
        commentary_blob = "\n".join(draft.commentary_items)
        self.assertIn("characteristic-quote:from=bebop:against=bossa-nova", commentary_blob)
        self.assertIn(
            "you're using bebop chords in bossa nova rhythm",
            commentary_blob,
        )

    def test_critique_emits_triangle_when_three_distinct_styles(self):
        # User said bossa, backing is gypsy, playing is bebop. All three
        # distinct → triangle commentary fires.
        passage = [
            DetectedVoicing(chord_symbol="Cmaj7", voicing_style_tags=("shell", "walking")),
        ]
        draft = critique_passage(passage, self.selection, candidate_styles=[
            self.bossa, self.bebop, self.gypsy, self.ralph_patt_style,
        ])
        commentary_blob = "\n".join(draft.commentary_items)
        self.assertIn("triangle:target=bossa-nova:backing=gypsy-jazz:detected=bebop", commentary_blob)

    def test_placeholder_warning_set_when_any_catalog_row_placeholder(self):
        passage = [
            DetectedVoicing(chord_symbol="Cmaj7", voicing_style_tags=("chromatic",)),
        ]
        draft = critique_passage(passage, self.selection, candidate_styles=[self.bossa])
        # All four styles in setUp() default to placeholder=True, so the
        # selection's catalog rows have placeholder=True → flag should fire.
        self.assertTrue(draft.placeholder_warning)

    def test_critique_handles_empty_passage_gracefully(self):
        draft = critique_passage([], self.selection, candidate_styles=[self.bossa])
        self.assertEqual(draft.style_match_score, 0.0)
        self.assertEqual(draft.detected_axes, {})

    def test_persist_critique_writes_db_row(self):
        passage = [
            DetectedVoicing(chord_symbol="Cmaj7", voicing_style_tags=("chromatic", "shell")),
        ]
        draft = critique_passage(passage, self.selection, candidate_styles=[
            self.bossa, self.bebop,
        ])
        critique = persist_critique(draft, audio_input_ref="audio:test:1")
        critique.refresh_from_db()
        self.assertEqual(critique.selection_id, self.selection.pk)
        self.assertEqual(critique.audio_input_ref, "audio:test:1")
        self.assertGreater(len(critique.commentary), 0)
        self.assertEqual(Critique.objects.count(), 1)


# ---------------------------------------------------------------------------
# Seed catalog tests
# ---------------------------------------------------------------------------


from io import StringIO
from django.core.management import call_command


class SeedStyleCatalogCommandTests(TestCase):
    def test_seeds_8_styles_and_4_idioms(self):
        call_command("seed_style_catalog", stdout=StringIO())
        self.assertEqual(Style.objects.count(), 8)
        self.assertEqual(Idiom.objects.count(), 4)

    def test_seeded_rows_are_placeholder(self):
        call_command("seed_style_catalog", stdout=StringIO())
        self.assertTrue(all(s.is_placeholder for s in Style.objects.all()))
        self.assertTrue(all(i.is_placeholder for i in Idiom.objects.all()))

    def test_idempotent_re_run(self):
        call_command("seed_style_catalog", stdout=StringIO())
        call_command("seed_style_catalog", stdout=StringIO())
        self.assertEqual(Style.objects.count(), 8)
        self.assertEqual(Idiom.objects.count(), 4)

    def test_real_catalog_rows_are_preserved_on_reseed(self):
        # Simulate sub-E's catalog-sync replacing one row with real content
        call_command("seed_style_catalog", stdout=StringIO())
        bebop = Style.objects.get(slug="bebop")
        bebop.is_placeholder = False
        bebop.description = "REAL CONTENT FROM PLUGIN AGENT'S DISTILLATION"
        bebop.save()

        # Re-run seed — bebop should NOT be touched
        out = StringIO()
        call_command("seed_style_catalog", stdout=out)
        bebop.refresh_from_db()
        self.assertFalse(bebop.is_placeholder)
        self.assertEqual(
            bebop.description, "REAL CONTENT FROM PLUGIN AGENT'S DISTILLATION",
        )
        self.assertIn("skip bebop", out.getvalue())

    def test_force_overwrite_clobbers_real_rows(self):
        call_command("seed_style_catalog", stdout=StringIO())
        bebop = Style.objects.get(slug="bebop")
        bebop.is_placeholder = False
        bebop.description = "REAL CONTENT"
        bebop.save()

        # With --force-overwrite, even real rows are clobbered back to placeholder
        call_command("seed_style_catalog", "--force-overwrite", stdout=StringIO())
        bebop.refresh_from_db()
        self.assertTrue(bebop.is_placeholder)
        self.assertNotIn("REAL CONTENT", bebop.description)

    def test_seeded_bebop_has_divergence_notes_against_bossa(self):
        call_command("seed_style_catalog", stdout=StringIO())
        bebop = Style.objects.get(slug="bebop")
        notes = bebop.divergence_notes
        bossa_note = next((n for n in notes if n["vs_style"] == "bossa-nova"), None)
        self.assertIsNotNone(bossa_note)
        self.assertIn("bebop chords in bossa nova rhythm", bossa_note["characteristic_quote"])

    def test_comparator_runs_against_seeded_data(self):
        """The whole point of the seed: the comparator should produce a
        non-trivial CritiqueDraft against the seeded catalog WITHOUT real
        plugin content.
        """
        from apps.styles.comparator import DetectedVoicing, critique_passage

        call_command("seed_style_catalog", stdout=StringIO())

        user = User.objects.create(username="seed-test")
        bossa = Style.objects.get(slug="bossa-nova")
        gypsy = Style.objects.get(slug="gypsy-jazz")
        target = StylePreset.objects.create(slug="t-seed", display_name="t", style=bossa)
        backing = StylePreset.objects.create(slug="b-seed", display_name="b", style=gypsy)
        sel = StyleSelection.objects.create(
            user=user, target_preset=target, backing_preset=backing,
        )

        # Passage uses shell + walking + chromatic — bebop's affinity tags
        passage = [
            DetectedVoicing(
                chord_symbol="Cmaj7",
                voicing_style_tags=("shell", "walking-bass", "chromatic"),
            ),
        ]
        draft = critique_passage(passage, sel)
        # Comparator should detect bebop and pull the characteristic quote
        self.assertEqual(draft.detected_axes["style"]["slug"], "bebop")
        commentary = "\n".join(draft.commentary_items)
        self.assertIn("bebop chords in bossa nova rhythm", commentary)
        self.assertIn("triangle:target=bossa-nova:backing=gypsy-jazz:detected=bebop", commentary)
