"""Tests for apps.voicings (#186 Phase 2)."""

from __future__ import annotations

import json
import secrets
import tempfile
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.voicings.fretboard import render_svg
from apps.voicings.models import Voicing, VoicingBundle


User = get_user_model()


def _make_bundle(sha: str = "a" * 40, active: bool = True) -> VoicingBundle:
    return VoicingBundle.objects.create(
        plugin_commit_sha=sha,
        source_url="https://example.invalid/voicings.json",
        built_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
        total_voicings=0,
        raw_top_level={},
        is_active=active,
    )


def _make_voicing(bundle: VoicingBundle, **overrides) -> Voicing:
    defaults = dict(
        bundle=bundle,
        voicing_id="c-maj7-shell-6str-1",
        name="Cmaj7 — Shell — E str",
        chord_quality="maj7",
        root="C",
        category="shell",
        suitable_modes=["comping"],
        strings=6,
        tuning="",
        fret_number=3,
        visible_frets=4,
        dots=[{"string": 6, "fret": 1}, {"string": 4, "fret": 2}, {"string": 3, "fret": 1}],
        mutes=[5],
        open_strings=[1],
        notes=["C", "B", "E"],
        intervals=["1", "7", "3"],
        tags=["shell"],
        also_qualities=[],
        shape_id="abcd1234",
        is_active=True,
    )
    defaults.update(overrides)
    return Voicing.objects.create(**defaults)


class VoicingModelTests(TestCase):
    def test_unique_per_bundle_voicing_id(self):
        bundle = _make_bundle()
        _make_voicing(bundle)
        with self.assertRaises(IntegrityError), transaction.atomic():
            _make_voicing(bundle)  # same voicing_id

    def test_same_voicing_id_across_bundles_ok(self):
        b1 = _make_bundle(sha="a" * 40, active=False)
        b2 = _make_bundle(sha="b" * 40, active=True)
        _make_voicing(b1)
        _make_voicing(b2)  # same voicing_id, different bundle — allowed

    def test_unique_per_plugin_sha(self):
        _make_bundle(sha="c" * 40)
        with self.assertRaises(IntegrityError), transaction.atomic():
            _make_bundle(sha="c" * 40)


class FretboardSVGTests(TestCase):
    def test_render_returns_svg_with_dots(self):
        svg = render_svg(
            strings=6,
            fret_number=3,
            visible_frets=4,
            dots=[{"string": 6, "fret": 1}, {"string": 4, "fret": 2}],
            mutes=[5],
            open_strings=[1],
        )
        self.assertIn("<svg", svg)
        self.assertIn("</svg>", svg)
        self.assertIn("<circle", svg)  # at least one dot rendered
        self.assertIn("3fr", svg)  # position label when fret_number != 0

    def test_nut_render_when_fret_zero(self):
        svg = render_svg(
            strings=6, fret_number=0, visible_frets=4,
            dots=[], mutes=[], open_strings=[1, 2, 3, 4, 5, 6],
        )
        self.assertIn("<rect", svg)  # the nut indicator
        self.assertNotIn("0fr", svg)

    def test_out_of_range_dots_are_skipped(self):
        # string=99 and fret=99 are out of bounds; render should not crash
        svg = render_svg(
            strings=6, fret_number=1, visible_frets=4,
            dots=[{"string": 99, "fret": 1}, {"string": 1, "fret": 99}],
        )
        self.assertIn("<svg", svg)
        # No <circle> from the dots (only out-of-range)
        self.assertNotIn("r=\"6\"", svg)

    def test_empty_diagram_when_invalid_geometry(self):
        self.assertEqual(render_svg(strings=0, fret_number=0, visible_frets=0, dots=[]), "")


class VoicingListViewTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.maj7 = _make_voicing(
            self.bundle,
            voicing_id="cmaj7-1", chord_quality="maj7", category="shell",
        )
        self.dom7 = _make_voicing(
            self.bundle,
            voicing_id="cdom7-1", chord_quality="dom7", category="drop2",
        )
        self.user = User.objects.create_user(
            username="trevor", password=secrets.token_urlsafe(16),
        )

    def test_login_required(self):
        response = self.client.get(reverse("voicings:voicing_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_list_renders_active_voicings(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("voicings:voicing_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.maj7.name)
        self.assertContains(response, self.dom7.name)

    def test_quality_filter(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("voicings:voicing_list") + "?quality=maj7"
        )
        self.assertContains(response, self.maj7.name)
        self.assertNotContains(response, self.dom7.name)

    def test_category_filter(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("voicings:voicing_list") + "?category=drop2"
        )
        self.assertContains(response, self.dom7.name)
        self.assertNotContains(response, self.maj7.name)

    def test_inactive_voicings_hidden(self):
        self.maj7.is_active = False
        self.maj7.save(update_fields=["is_active"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("voicings:voicing_list"))
        self.assertNotContains(response, self.maj7.name)
        self.assertContains(response, self.dom7.name)


class VoicingDetailViewTests(TestCase):
    def setUp(self):
        self.bundle = _make_bundle()
        self.voicing = _make_voicing(self.bundle)
        self.user = User.objects.create_user(
            username="trevor", password=secrets.token_urlsafe(16),
        )

    def test_detail_renders_svg(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("voicings:voicing_detail", args=[self.voicing.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<svg")
        self.assertContains(response, self.voicing.voicing_id)

    def test_detail_404_for_inactive(self):
        self.voicing.is_active = False
        self.voicing.save(update_fields=["is_active"])
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("voicings:voicing_detail", args=[self.voicing.pk])
        )
        self.assertEqual(response.status_code, 404)


class SyncVoicingsCommandTests(TestCase):
    """Round-trip a fixture file through sync_voicings.

    Uses a 3-voicing fixture (smaller than real 820) so the test is fast
    while still exercising the full pipeline: load -> bundle create ->
    bulk insert -> activate -> deactivate prior.
    """

    FIXTURE = {
        "voicings": [
            {
                "id": "cmaj7-shell-1",
                "name": "Cmaj7 — Shell 137",
                "chord_quality": "maj7",
                "root": "C",
                "category": "shell",
                "suitableModes": ["comping"],
                "strings": 6,
                "fret_number": 3,
                "visible_frets": 4,
                "dots": [{"string": 6, "fret": 1}, {"string": 4, "fret": 2}],
                "mutes": [5],
                "open": [1],
                "notes": ["C", "B", "E"],
                "intervals": ["1", "7", "3"],
                "tags": ["shell"],
                "also_qualities": [],
            },
            {
                "id": "cdom7-drop2-1",
                "name": "C7 — Drop2",
                "chord_quality": "dom7",
                "root": "C",
                "category": "drop2",
                "suitableModes": ["chord-melody"],
                "strings": 6,
                "fret_number": 5,
                "visible_frets": 4,
                "dots": [{"string": 4, "fret": 1}],
                "mutes": [],
                "open": [],
                "notes": ["C", "E", "Bb"],
                "intervals": ["1", "3", "b7"],
                "tags": [],
                "also_qualities": [],
            },
            {
                "id": "cmin7-shell-1",
                "name": "Cm7 — Shell",
                "chord_quality": "min7",
                "root": "C",
                "category": "shell",
                "suitableModes": ["comping"],
                "strings": 6,
                "fret_number": 3,
                "visible_frets": 4,
                "dots": [{"string": 6, "fret": 1}],
                "mutes": [],
                "open": [],
                "notes": ["C", "Eb", "Bb"],
                "intervals": ["1", "b3", "b7"],
                "tags": [],
                "also_qualities": [],
            },
        ],
    }

    def _write_fixture(self, payload=None) -> str:
        payload = payload or self.FIXTURE
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        json.dump(payload, tmp)
        tmp.close()
        return tmp.name

    def test_round_trip_local(self):
        path = self._write_fixture()
        call_command(
            "sync_voicings",
            local_path=path,
            plugin_sha="d" * 40,
            built_at="2026-06-24T13:00:00Z",
        )
        bundle = VoicingBundle.objects.get(plugin_commit_sha="d" * 40)
        self.assertTrue(bundle.is_active)
        self.assertEqual(bundle.total_voicings, 3)
        self.assertEqual(Voicing.objects.filter(bundle=bundle).count(), 3)
        cmaj7 = Voicing.objects.get(voicing_id="cmaj7-shell-1")
        self.assertEqual(cmaj7.open_strings, [1])
        self.assertEqual(cmaj7.mutes, [5])
        self.assertTrue(cmaj7.is_active)

    def test_idempotent_on_same_sha(self):
        path = self._write_fixture()
        call_command(
            "sync_voicings", local_path=path, plugin_sha="e" * 40,
        )
        call_command(
            "sync_voicings", local_path=path, plugin_sha="e" * 40,
        )
        self.assertEqual(
            VoicingBundle.objects.filter(plugin_commit_sha="e" * 40).count(),
            1,
        )
        self.assertEqual(Voicing.objects.count(), 3)

    def test_new_bundle_deactivates_prior(self):
        path = self._write_fixture()
        call_command(
            "sync_voicings", local_path=path, plugin_sha="f" * 40,
        )
        call_command(
            "sync_voicings", local_path=path, plugin_sha="9" * 40,
        )
        old = VoicingBundle.objects.get(plugin_commit_sha="f" * 40)
        new = VoicingBundle.objects.get(plugin_commit_sha="9" * 40)
        self.assertFalse(old.is_active)
        self.assertTrue(new.is_active)
        self.assertEqual(
            Voicing.objects.filter(bundle=old, is_active=True).count(), 0,
        )
        self.assertEqual(
            Voicing.objects.filter(bundle=new, is_active=True).count(), 3,
        )

    def test_missing_voicings_key_rejected(self):
        path = self._write_fixture({"wrong_key": []})
        with self.assertRaises(Exception):
            call_command(
                "sync_voicings", local_path=path, plugin_sha="0" * 40,
            )

    def test_empty_voicings_array_rejected(self):
        path = self._write_fixture({"voicings": []})
        with self.assertRaises(Exception):
            call_command(
                "sync_voicings", local_path=path, plugin_sha="1" * 40,
            )

    def test_synthetic_quality_accepted(self):
        """Plugin schema allows free-text chord_quality; ingest must not enum-gate."""
        payload = {
            "voicings": [
                {
                    "id": "exotic-1",
                    "name": "Exotic voicing",
                    "chord_quality": "dom13#11b9",  # synthetic, not pre-known
                    "root": "C",
                    "category": "altered",
                    "suitableModes": ["solo-guitar"],
                    "strings": 6,
                    "fret_number": 7,
                    "visible_frets": 4,
                    "dots": [{"string": 6, "fret": 1}],
                    "mutes": [],
                    "open": [],
                    "notes": ["C"],
                    "intervals": ["1"],
                    "tags": [],
                    "also_qualities": [],
                },
            ],
        }
        path = self._write_fixture(payload)
        call_command(
            "sync_voicings", local_path=path, plugin_sha="2" * 40,
        )
        v = Voicing.objects.get(voicing_id="exotic-1")
        self.assertEqual(v.chord_quality, "dom13#11b9")
