"""Idempotent seeder for placeholder Style + Idiom catalog rows.

Best-effort tag affinity / signature / divergence_notes guesses so the
comparator (apps.styles.comparator) has something substantive to chew
on before plugin agent's distillation pass produces real prescriptive
content. Every seeded row is marked ``is_placeholder=True`` so admins
can see at a glance what's still synthetic. Sub-E's catalog-sync
command will flip ``is_placeholder=False`` on rows it replaces with
plugin-authored content.

Idempotency: ``update_or_create`` by slug. Re-running is safe and
overwrites placeholder content (but NEVER touches rows where
``is_placeholder=False`` — that's the catalog-sync's territory).

The cross-style ``divergence_notes`` are the highest-leverage payload
here: they're what makes the comparator's bossa-vs-bebop critique
sound like a comper who knows both languages. The placeholder quotes
below are deliberately small + honest about being placeholders — the
plugin agent's distillation pass will replace them with quotes
extracted from the source material.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.styles.models import Idiom, Style


# ---------------------------------------------------------------------------
# Placeholder catalog data
# ---------------------------------------------------------------------------


STYLE_SEEDS: list[dict] = [
    {
        "slug": "berklee-consensus",
        "name": "Berklee Consensus",
        "description": (
            "The implicit baseline most music-school students get taught: "
            "shell voicings, drop-2 / drop-3, ii-V-I patterns, traditional "
            "voice-leading. Not a tradition per se — a pedagogical default."
        ),
        "voicing_style_tag_affinity": {
            "drop-2": 1.0,
            "drop-3": 0.8,
            "shell": 1.0,
            "traditional": 1.0,
            "voice-led": 0.9,
        },
        "rhythmic_signature": {
            "subdivision": "8ths",
            "density": "medium",
            "onset_anticipation": "on-beat",
        },
        "harmonic_signature": {
            "chromatic_motion_tolerance": "medium",
            "substitution_density": "medium",
        },
        "divergence_notes": [
            {
                "vs_style": "bebop",
                "shared_dimensions": ["chromatic_motion_tolerance", "shell"],
                "diverging_dimensions": ["rhythmic_density", "onset_anticipation"],
                "characteristic_quote": (
                    "PLACEHOLDER — a Berklee-trained player would say this is a "
                    "bebop accent on a textbook ii-V-I."
                ),
            },
        ],
    },
    {
        "slug": "bebop",
        "name": "Bebop",
        "description": (
            "Parker / Powell / Pass lineage. Anticipated 8ths with chromatic "
            "passing, shell voicings under single-line, dense substitution "
            "vocabulary."
        ),
        "voicing_style_tag_affinity": {
            "shell": 1.0,
            "chromatic": 1.0,
            "walking-bass": 0.7,
            "drop-2": 0.9,
            "tritone-sub": 0.8,
        },
        "rhythmic_signature": {
            "subdivision": "8ths",
            "density": "dense",
            "onset_anticipation": "anticipated",
        },
        "harmonic_signature": {
            "chromatic_motion_tolerance": "high",
            "substitution_density": "high",
        },
        "divergence_notes": [
            {
                "vs_style": "bossa-nova",
                "shared_dimensions": ["chromatic_motion_tolerance"],
                "diverging_dimensions": ["rhythmic_signature", "onset_anticipation"],
                "characteristic_quote": (
                    "PLACEHOLDER — you're using bebop chords in bossa nova rhythm."
                ),
            },
            {
                "vs_style": "cool-jazz",
                "shared_dimensions": ["substitution_density"],
                "diverging_dimensions": ["density", "harmonic_temperature"],
                "characteristic_quote": (
                    "PLACEHOLDER — that's bebop reaching for a cool-jazz palette."
                ),
            },
        ],
    },
    {
        "slug": "bossa-nova",
        "name": "Bossa Nova",
        "description": (
            "Jobim / Gilberto lineage. Anticipated bass on the up of beat "
            "4, sparse comping voicings, melody-led harmonic motion."
        ),
        "voicing_style_tag_affinity": {
            "anticipated-bass": 1.0,
            "sparse": 0.9,
            "drop-2": 0.7,
            "chromatic": 0.6,
            "string-2-to-4-cluster": 0.7,
        },
        "rhythmic_signature": {
            "subdivision": "16ths",
            "density": "sparse",
            "onset_anticipation": "anticipated",
        },
        "harmonic_signature": {
            "chromatic_motion_tolerance": "medium",
            "substitution_density": "low",
        },
        "divergence_notes": [
            {
                "vs_style": "bebop",
                "shared_dimensions": ["chromatic_motion_tolerance"],
                "diverging_dimensions": ["density", "onset_anticipation"],
                "characteristic_quote": (
                    "PLACEHOLDER — bossa wants you to breathe; the bebop "
                    "density is filling all the air."
                ),
            },
        ],
    },
    {
        "slug": "cool-jazz",
        "name": "Cool Jazz",
        "description": (
            "Lee Konitz / Lennie Tristano / early Miles lineage. Smooth "
            "voice-leading, suspended tensions, deliberate restraint, "
            "polyphonic counterpoint over functional harmony."
        ),
        "voicing_style_tag_affinity": {
            "suspended": 0.9,
            "shell": 0.8,
            "drop-2": 0.8,
            "chromatic": 0.7,
            "polyphonic": 1.0,
        },
        "rhythmic_signature": {
            "subdivision": "8ths",
            "density": "medium",
            "onset_anticipation": "on-beat",
        },
        "harmonic_signature": {
            "chromatic_motion_tolerance": "high",
            "substitution_density": "medium",
            "harmonic_temperature": "cool",
        },
        "divergence_notes": [],
    },
    {
        "slug": "gypsy-jazz",
        "name": "Gypsy Jazz",
        "description": (
            "Django / Hot Club de France lineage. Arpeggiated comping, "
            "string-sweep rest-stroke right-hand technique, dominant-"
            "diminished altered scale vocabulary, walking-bass underneath."
        ),
        "voicing_style_tag_affinity": {
            "arpeggiated": 1.0,
            "string-sweep": 0.9,
            "diminished": 0.8,
            "walking-bass": 0.7,
            "altered-dom": 0.8,
        },
        "rhythmic_signature": {
            "subdivision": "8ths",
            "density": "dense",
            "onset_anticipation": "on-beat",
        },
        "harmonic_signature": {
            "chromatic_motion_tolerance": "high",
            "substitution_density": "medium",
        },
        "divergence_notes": [],
    },
    {
        "slug": "modal",
        "name": "Modal",
        "description": (
            "Post-Kind-of-Blue Miles / Coltrane lineage. Sustained pedal "
            "tonality, quartal voicings, slow chord rhythm, modal "
            "interchange replaces functional harmony."
        ),
        "voicing_style_tag_affinity": {
            "quartal": 1.0,
            "sus": 0.9,
            "open-voicing": 0.8,
            "pedal-friendly": 0.9,
        },
        "rhythmic_signature": {
            "subdivision": "8ths",
            "density": "sparse",
            "onset_anticipation": "on-beat",
        },
        "harmonic_signature": {
            "chromatic_motion_tolerance": "low",
            "substitution_density": "low",
            "modal_interchange": "high",
        },
        "divergence_notes": [],
    },
    {
        "slug": "standards",
        "name": "Standards / Tin Pan Alley",
        "description": (
            "The harmonic substrate everything sits on top of — Gershwin / "
            "Porter / Kern. Diatonic ii-V-I vocabulary, occasional secondary "
            "dominants, song-form-driven phrasing. The 'unmarked' style."
        ),
        "voicing_style_tag_affinity": {
            "drop-2": 1.0,
            "shell": 1.0,
            "voice-led": 1.0,
            "diatonic": 1.0,
        },
        "rhythmic_signature": {
            "subdivision": "8ths",
            "density": "medium",
            "onset_anticipation": "on-beat",
        },
        "harmonic_signature": {
            "chromatic_motion_tolerance": "low",
            "substitution_density": "low",
        },
        "divergence_notes": [],
    },
    {
        "slug": "chord-melody-tradition",
        "name": "Chord-Melody Tradition",
        "description": (
            "George Van Eps / Lenny Breau / Joe Pass solo-guitar lineage. "
            "Melody on top + bass on bottom + inner harmony — all in one "
            "instrument. Idiom-adjacent but distinct in voicing density."
        ),
        "voicing_style_tag_affinity": {
            "wide-voicing": 1.0,
            "melody-on-top": 1.0,
            "bass-line-integrated": 1.0,
            "drop-3": 0.9,
        },
        "rhythmic_signature": {
            "subdivision": "8ths",
            "density": "medium",
            "onset_anticipation": "on-beat",
        },
        "harmonic_signature": {
            "chromatic_motion_tolerance": "high",
            "substitution_density": "medium",
        },
        "divergence_notes": [],
    },
]


IDIOM_SEEDS: list[dict] = [
    {
        "slug": "chord-melody",
        "name": "Chord Melody",
        "description": (
            "Melody on top + integrated bass + inner voices. Solo-guitar "
            "performance context. Van Eps / Breau / Joe Pass."
        ),
        "performance_context_metadata": {
            "voice_count_typical": [3, 4, 5],
            "tempo_range_bpm": [60, 160],
            "ensemble": "solo",
        },
    },
    {
        "slug": "comping",
        "name": "Comping",
        "description": (
            "Rhythm-section accompaniment behind a soloist. Sparse, "
            "responsive, leaves space for melody."
        ),
        "performance_context_metadata": {
            "voice_count_typical": [2, 3, 4],
            "tempo_range_bpm": [60, 280],
            "ensemble": "combo",
        },
    },
    {
        "slug": "single-line",
        "name": "Single-line",
        "description": (
            "Melodic improvisation — one note at a time. Not voicing-"
            "centric per se but covered here for completeness; voicing-"
            "style tags appear as colour notes in arpeggiations."
        ),
        "performance_context_metadata": {
            "voice_count_typical": [1],
            "tempo_range_bpm": [60, 320],
            "ensemble": "any",
        },
    },
    {
        "slug": "walking-bass-with-chords",
        "name": "Walking Bass with Chords",
        "description": (
            "Joe Pass / Tuck Andress / Martin Taylor lineage. Walking "
            "bass on the bottom string(s) + chord stabs on the upper "
            "strings — duo-format guitar context."
        ),
        "performance_context_metadata": {
            "voice_count_typical": [3, 4],
            "tempo_range_bpm": [80, 220],
            "ensemble": "duo",
        },
    },
]


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = (
        "Seed placeholder Style and Idiom catalog rows so the comparator "
        "has substantive data before the plugin agent's distillation pass "
        "produces real catalogs. Idempotent — safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite-placeholders-only",
            action="store_true",
            default=True,
            help=(
                "When set (default), only update rows where "
                "is_placeholder=True. Real rows (catalog-sync'd content) "
                "stay untouched. Negate with --force-overwrite for testing."
            ),
        )
        parser.add_argument(
            "--force-overwrite",
            action="store_true",
            default=False,
            help=(
                "DANGEROUS: overwrite ALL matching rows including real "
                "catalog content. Use only in tests."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        force = options.get("force_overwrite", False)

        styles_touched = self._seed_styles(force=force)
        idioms_touched = self._seed_idioms(force=force)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {styles_touched} Style and {idioms_touched} Idiom rows "
                f"(placeholder=True). Use admin to inspect; the comparator "
                f"will pick them up automatically."
            )
        )

    def _seed_styles(self, *, force: bool) -> int:
        touched = 0
        for seed in STYLE_SEEDS:
            existing = Style.objects.filter(slug=seed["slug"]).first()
            if existing and not existing.is_placeholder and not force:
                self.stdout.write(
                    self.style.WARNING(
                        f"  skip {seed['slug']} — already catalog-sync'd "
                        f"(is_placeholder=False); use --force-overwrite to override"
                    )
                )
                continue
            Style.objects.update_or_create(
                slug=seed["slug"],
                defaults={
                    "name": seed["name"],
                    "description": seed["description"],
                    "voicing_style_tag_affinity": seed["voicing_style_tag_affinity"],
                    "rhythmic_signature": seed["rhythmic_signature"],
                    "harmonic_signature": seed["harmonic_signature"],
                    "divergence_notes": seed["divergence_notes"],
                    "is_placeholder": True,
                    "schema_version": "v1",
                },
            )
            touched += 1
        return touched

    def _seed_idioms(self, *, force: bool) -> int:
        touched = 0
        for seed in IDIOM_SEEDS:
            existing = Idiom.objects.filter(slug=seed["slug"]).first()
            if existing and not existing.is_placeholder and not force:
                self.stdout.write(
                    self.style.WARNING(
                        f"  skip {seed['slug']} — already catalog-sync'd; "
                        f"use --force-overwrite to override"
                    )
                )
                continue
            Idiom.objects.update_or_create(
                slug=seed["slug"],
                defaults={
                    "name": seed["name"],
                    "description": seed["description"],
                    "performance_context_metadata": seed["performance_context_metadata"],
                    "is_placeholder": True,
                    "schema_version": "v1",
                },
            )
            touched += 1
        return touched
