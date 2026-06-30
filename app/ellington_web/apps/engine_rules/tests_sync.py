"""Tests for the engine-rules data layer and the sync_engine_rules command.

Bundle parsing + DB-write tests run against an in-memory tarball
constructed at test time — no network, no external bundle file. The
shape of the synthetic bundle matches the contract Plugin #547 ships
(``manifest.json`` + ``masters/<m>/<w>/derived/engine-rules.json``).
"""

from __future__ import annotations

import io
import json
import tarfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.engine_rules.management.commands import sync_engine_rules
from apps.engine_rules.models import EngineRule, EngineRulesBundle
from apps.styles.models import Master


def _build_bundle(
    manifest: dict | None = None,
    rules_files: dict[str, dict] | None = None,
) -> bytes:
    """Construct an in-memory engine-rules bundle tarball."""
    manifest = manifest or {
        "schema_version": "0.1",
        "bundle_version": "0.1.0",
        "min_consumer_version": "0.1.0",
        "plugin_commit_sha": "a" * 40,
        "built_at": "2026-06-17T19:30:00+00:00",
        "total_rules": 1,
        "masters": [],
    }
    rules_files = rules_files or {
        "masters/joe-pass/guitar-chords/derived/engine-rules.json": {
            "engine_rules": [
                {
                    "rule_id": "r-001",
                    "name": "Use rootless dom7 over II-V",
                    "preference": 2,
                    "quality_binding": ["dom7"],
                    "when": {"chord_quality": "dom7", "context": "two_five_one"},
                    "then": {"voicing_family": "rootless"},
                    "falsifier": "if voicing has root, rule violated",
                    "anchor": "Pass, p.47",
                    "source_page": 47,
                }
            ]
        }
    }

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        m_bytes = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(m_bytes)
        tar.addfile(info, io.BytesIO(m_bytes))
        for path, payload in rules_files.items():
            data = json.dumps(payload).encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestSyncEngineRulesHappyPath(TestCase):
    """Bundle with one master/one work/one rule → sync upserts cleanly."""

    def setUp(self) -> None:
        # Master must exist before sync — production has the same
        # ordering constraint (sync_plugin_catalogs runs first).
        Master.objects.create(
            slug="joe-pass",
            name="Joe Pass",
            is_placeholder=False,
        )
        self.bundle_bytes = _build_bundle()

    def _call(self, **kwargs) -> StringIO:
        out = StringIO()
        path = Path("/tmp/test-engine-rules-bundle.tar.gz")
        path.write_bytes(self.bundle_bytes)
        call_command(
            "sync_engine_rules",
            "--bundle-path", str(path),
            stdout=out,
            **kwargs,
        )
        return out

    def test_creates_bundle_row(self) -> None:
        self._call()
        b = EngineRulesBundle.objects.get()
        self.assertEqual(b.bundle_version, "0.1.0")
        self.assertEqual(b.schema_version, "0.1")
        self.assertEqual(b.plugin_commit_sha, "a" * 40)
        self.assertEqual(b.total_rules, 1)
        # Manifest preserved verbatim
        self.assertEqual(b.manifest["min_consumer_version"], "0.1.0")

    def test_creates_engine_rule_row(self) -> None:
        self._call()
        r = EngineRule.objects.get()
        self.assertEqual(r.rule_id, "r-001")
        self.assertEqual(r.name, "Use rootless dom7 over II-V")
        self.assertEqual(r.preference, 2)
        self.assertEqual(r.quality_binding, ["dom7"])
        self.assertEqual(r.when_predicate["chord_quality"], "dom7")
        self.assertEqual(r.then_action["voicing_family"], "rootless")
        self.assertEqual(r.master.slug, "joe-pass")
        self.assertEqual(r.work_id, "guitar-chords")
        self.assertTrue(r.is_active)
        self.assertEqual(r.polarity, "positive")

    def test_idempotent_re_run(self) -> None:
        """Re-syncing the same bundle is a no-op shape-wise."""
        self._call()
        b1_count = EngineRulesBundle.objects.count()
        r1_count = EngineRule.objects.count()
        self._call()
        self.assertEqual(EngineRulesBundle.objects.count(), b1_count)
        self.assertEqual(EngineRule.objects.count(), r1_count)


class TestSyncEngineRulesPolarity(TestCase):
    """Polarity is derived correctly from signed preferences."""

    def setUp(self) -> None:
        Master.objects.create(slug="joe-pass", name="Joe Pass")

    def _run_with_preference(self, pref: int) -> EngineRule:
        bundle_bytes = _build_bundle(
            rules_files={
                "masters/joe-pass/guitar-chords/derived/engine-rules.json": {
                    "engine_rules": [
                        {
                            "rule_id": f"r-{pref}",
                            "name": "test",
                            "preference": pref,
                            "quality_binding": [],
                            "when": {},
                            "then": {},
                        }
                    ]
                }
            }
        )
        path = Path(f"/tmp/test-engine-rules-pref-{pref}.tar.gz")
        path.write_bytes(bundle_bytes)
        call_command("sync_engine_rules", "--bundle-path", str(path), stdout=StringIO())
        return EngineRule.objects.get(rule_id=f"r-{pref}")

    def test_avoid_strong_polarity(self) -> None:
        self.assertEqual(self._run_with_preference(-2).polarity, "avoid")

    def test_avoid_weak_polarity(self) -> None:
        self.assertEqual(self._run_with_preference(-1).polarity, "avoid")

    def test_neutral_polarity(self) -> None:
        self.assertEqual(self._run_with_preference(0).polarity, "neutral")

    def test_recommend_weak_polarity(self) -> None:
        self.assertEqual(self._run_with_preference(1).polarity, "positive")

    def test_recommend_strong_polarity(self) -> None:
        self.assertEqual(self._run_with_preference(2).polarity, "positive")


class TestSyncEngineRulesValidation(TestCase):
    """min_consumer_version rejection + missing master skip."""

    def test_min_consumer_version_too_high_raises(self) -> None:
        bundle = _build_bundle(
            manifest={
                "schema_version": "0.1",
                "bundle_version": "0.2.0",
                "min_consumer_version": "999.0.0",
                "plugin_commit_sha": "b" * 40,
                "built_at": "2026-06-17T19:30:00+00:00",
                "total_rules": 0,
                "masters": [],
            },
            rules_files={},
        )
        path = Path("/tmp/test-engine-rules-too-new.tar.gz")
        path.write_bytes(bundle)
        with self.assertRaises(CommandError):
            call_command(
                "sync_engine_rules",
                "--bundle-path", str(path),
                stdout=StringIO(),
            )

    def test_missing_master_skipped_with_warning(self) -> None:
        # No Master.create — sync should skip the rule, not raise
        bundle = _build_bundle()  # references joe-pass master
        path = Path("/tmp/test-engine-rules-no-master.tar.gz")
        path.write_bytes(bundle)
        out = StringIO()
        call_command(
            "sync_engine_rules",
            "--bundle-path", str(path),
            stdout=out,
        )
        # Bundle row created, but no rules
        self.assertEqual(EngineRulesBundle.objects.count(), 1)
        self.assertEqual(EngineRule.objects.count(), 0)
        self.assertIn("not in DB", out.getvalue())

    def test_no_release_tag_no_bundle_path_raises(self) -> None:
        with self.assertRaises(CommandError):
            call_command("sync_engine_rules", stdout=StringIO())


class TestQualityBindingAliasTable(TestCase):
    """Legacy quality_binding tokens normalize to canonical chord types.

    Until plugin #555 lands the corpus migration, the sync command
    applies the firing-spec §2 alias table inline.
    """

    def setUp(self) -> None:
        Master.objects.create(slug="legacy-master", name="Legacy")

    def test_legacy_seventh_aliased_to_dom7(self) -> None:
        bundle_bytes = _build_bundle(
            rules_files={
                "masters/legacy-master/old-work/derived/engine-rules.json": {
                    "engine_rules": [
                        {
                            "rule_id": "r-leg",
                            "name": "legacy",
                            "preference": 1,
                            "quality_binding": ["seventh", "min7"],
                            "when": {},
                            "then": {},
                        }
                    ]
                }
            }
        )
        path = Path("/tmp/test-engine-rules-legacy.tar.gz")
        path.write_bytes(bundle_bytes)
        call_command("sync_engine_rules", "--bundle-path", str(path), stdout=StringIO())
        r = EngineRule.objects.get(rule_id="r-leg")
        # seventh → dom7; min7 IS canonical (per firing-spec v0.1 §2),
        # not aliased. Hostile-review correction on PR #99: my first
        # draft mapped min7 → m7 which would have corrupted canonical
        # data (m7 is not in the canonical token set).
        self.assertEqual(r.quality_binding, ["dom7", "min7"])

    def test_v01_path_layout_also_supported(self) -> None:
        """Tolerant regex accepts the v0.1.0 ``plugin/data/masters-corpus/...``
        layout in addition to v0.1.1+'s ``masters/...``. Hostile-review
        B2 on PR #99.
        """
        Master.objects.get_or_create(slug="legacy-master", name="Legacy")
        bundle_bytes = _build_bundle(
            rules_files={
                # v0.1.0 path prefix the plugin actually ships
                "plugin/data/masters-corpus/legacy-master/work-a/derived/engine-rules.json": {
                    "engine_rules": [
                        {"rule_id": "rv01", "name": "v0.1 path", "preference": 1,
                         "quality_binding": [], "when": {}, "then": {}},
                    ]
                }
            }
        )
        path = Path("/tmp/test-engine-rules-v01-path.tar.gz")
        path.write_bytes(bundle_bytes)
        call_command("sync_engine_rules", "--bundle-path", str(path), stdout=StringIO())
        # Rule landed despite the prefix mismatch with v0.1.1+ layout
        self.assertTrue(EngineRule.objects.filter(rule_id="rv01").exists())

    def test_canonical_tokens_pass_through(self) -> None:
        # Post-#555 bundles ship with canonical tokens already; the
        # alias table should be a no-op for them.
        bundle_bytes = _build_bundle(
            rules_files={
                "masters/legacy-master/canonical/derived/engine-rules.json": {
                    "engine_rules": [
                        {
                            "rule_id": "r-can",
                            "name": "canonical",
                            "preference": 1,
                            "quality_binding": ["dom7b9", "maj7", "dim7"],
                            "when": {},
                            "then": {},
                        }
                    ]
                }
            }
        )
        path = Path("/tmp/test-engine-rules-canonical.tar.gz")
        path.write_bytes(bundle_bytes)
        call_command("sync_engine_rules", "--bundle-path", str(path), stdout=StringIO())
        r = EngineRule.objects.get(rule_id="r-can")
        self.assertEqual(r.quality_binding, ["dom7b9", "maj7", "dim7"])


class TestDeactivationOfStaleRules(TestCase):
    """Re-syncing a bundle that omits a previously-imported rule marks
    that rule as is_active=False — never deletes it."""

    def setUp(self) -> None:
        Master.objects.create(slug="joe-pass", name="Joe Pass")

    def test_omitted_rule_becomes_inactive(self) -> None:
        # First sync: two rules
        first = _build_bundle(
            rules_files={
                "masters/joe-pass/guitar-chords/derived/engine-rules.json": {
                    "engine_rules": [
                        {"rule_id": "keep", "name": "keep", "preference": 1,
                         "quality_binding": [], "when": {}, "then": {}},
                        {"rule_id": "drop", "name": "drop", "preference": 1,
                         "quality_binding": [], "when": {}, "then": {}},
                    ]
                }
            }
        )
        path = Path("/tmp/test-engine-rules-first.tar.gz")
        path.write_bytes(first)
        call_command("sync_engine_rules", "--bundle-path", str(path), stdout=StringIO())
        self.assertEqual(EngineRule.objects.filter(is_active=True).count(), 2)

        # Second sync: new bundle (different SHA), only the kept rule
        second = _build_bundle(
            manifest={
                "schema_version": "0.1",
                "bundle_version": "0.1.1",
                "min_consumer_version": "0.1.0",
                "plugin_commit_sha": "b" * 40,
                "built_at": "2026-06-17T20:00:00+00:00",
                "total_rules": 1,
                "masters": [],
            },
            rules_files={
                "masters/joe-pass/guitar-chords/derived/engine-rules.json": {
                    "engine_rules": [
                        {"rule_id": "keep", "name": "keep", "preference": 1,
                         "quality_binding": [], "when": {}, "then": {}},
                    ]
                }
            }
        )
        path2 = Path("/tmp/test-engine-rules-second.tar.gz")
        path2.write_bytes(second)
        call_command("sync_engine_rules", "--bundle-path", str(path2), stdout=StringIO())

        # The dropped rule survives but is inactive; the kept rule
        # exists for both bundles (new row in the second bundle's name).
        dropped = EngineRule.objects.filter(rule_id="drop")
        self.assertEqual(dropped.count(), 1)
        self.assertFalse(dropped.first().is_active)
        # Total kept (active) = 1 (from second bundle)
        self.assertEqual(EngineRule.objects.filter(is_active=True).count(), 1)


class TestMassDeactivationGuard(TestCase):
    """The 50% sanity guard refuses syncs that would mass-deactivate rules.

    Plugin-agent Q3 ask on PR #99. Catches the accidental empty-bundle
    scenario; legitimate restructure still possible with --force.
    """

    def setUp(self) -> None:
        Master.objects.create(slug="joe-pass", name="Joe Pass")

    def _seed_n_rules(self, n: int) -> None:
        """Populate N active rules via a synthetic first-sync."""
        rules = [
            {
                "rule_id": f"r-{i}",
                "name": f"rule {i}",
                "preference": 1,
                "quality_binding": [],
                "when": {},
                "then": {},
            }
            for i in range(n)
        ]
        bundle = _build_bundle(
            manifest={
                "schema_version": "0.1",
                "bundle_version": "0.0.1",
                "min_consumer_version": "0.1.0",
                "plugin_commit_sha": "1" * 40,
                "built_at": "2026-06-17T00:00:00+00:00",
                "total_rules": n,
                "masters": [],
            },
            rules_files={
                "masters/joe-pass/big-corpus/derived/engine-rules.json": {
                    "engine_rules": rules
                }
            },
        )
        path = Path("/tmp/test-engine-rules-seed.tar.gz")
        path.write_bytes(bundle)
        call_command("sync_engine_rules", "--bundle-path", str(path), stdout=StringIO())

    def test_refuses_shrinking_bundle_without_force(self) -> None:
        self._seed_n_rules(10)
        # Sync with a near-empty bundle (1 rule vs 10 prior — 10% retained)
        small = _build_bundle(
            manifest={
                "schema_version": "0.1",
                "bundle_version": "0.0.2",
                "min_consumer_version": "0.1.0",
                "plugin_commit_sha": "2" * 40,
                "built_at": "2026-06-17T01:00:00+00:00",
                "total_rules": 1,
                "masters": [],
            },
            rules_files={
                "masters/joe-pass/big-corpus/derived/engine-rules.json": {
                    "engine_rules": [
                        {"rule_id": "r-0", "name": "one survivor",
                         "preference": 1, "quality_binding": [],
                         "when": {}, "then": {}},
                    ]
                }
            },
        )
        path = Path("/tmp/test-engine-rules-shrunk.tar.gz")
        path.write_bytes(small)
        with self.assertRaises(CommandError) as cm:
            call_command("sync_engine_rules", "--bundle-path", str(path), stdout=StringIO())
        self.assertIn("sanity guard", str(cm.exception))

    def test_force_overrides_guard(self) -> None:
        self._seed_n_rules(10)
        small = _build_bundle(
            manifest={
                "schema_version": "0.1",
                "bundle_version": "0.0.3",
                "min_consumer_version": "0.1.0",
                "plugin_commit_sha": "3" * 40,
                "built_at": "2026-06-17T02:00:00+00:00",
                "total_rules": 1,
                "masters": [],
            },
            rules_files={
                "masters/joe-pass/big-corpus/derived/engine-rules.json": {
                    "engine_rules": [
                        {"rule_id": "r-0", "name": "one survivor",
                         "preference": 1, "quality_binding": [],
                         "when": {}, "then": {}},
                    ]
                }
            },
        )
        path = Path("/tmp/test-engine-rules-force.tar.gz")
        path.write_bytes(small)
        # --force lets it proceed
        call_command(
            "sync_engine_rules",
            "--bundle-path", str(path),
            "--force",
            stdout=StringIO(),
        )
        # 9 of 10 prior rules deactivated, 1 survives + 1 new = 1 active
        self.assertEqual(EngineRule.objects.filter(is_active=True).count(), 1)

    def test_first_ever_sync_not_guarded(self) -> None:
        """No prior rules → guard skipped (first-ever sync is always OK)."""
        # No seed call; pristine DB
        bundle = _build_bundle()  # default fixture, 1 rule
        path = Path("/tmp/test-engine-rules-first.tar.gz")
        path.write_bytes(bundle)
        # Should NOT raise — first-ever sync skips the threshold check
        call_command("sync_engine_rules", "--bundle-path", str(path), stdout=StringIO())
        self.assertEqual(EngineRule.objects.filter(is_active=True).count(), 1)


class TestSemverHelper(TestCase):
    """Sanity for the inline semver comparator."""

    def test_consumer_meets_lower_min(self) -> None:
        self.assertFalse(sync_engine_rules._semver_gt("0.0.5", "0.1.0"))

    def test_consumer_below_min(self) -> None:
        self.assertTrue(sync_engine_rules._semver_gt("0.2.0", "0.1.0"))

    def test_equal_versions(self) -> None:
        self.assertFalse(sync_engine_rules._semver_gt("0.1.0", "0.1.0"))


# ---------------------------------------------------------------------------
# #157 — --latest-release resolver
# ---------------------------------------------------------------------------


from unittest.mock import patch, MagicMock  # noqa: E402

from apps.engine_rules.management.commands.sync_engine_rules import Command  # noqa: E402


class LatestReleaseResolverTests(TestCase):
    """The --latest-release flag picks the highest-semver tag from
    the plugin's GitHub Releases API."""

    def _mock_releases(self, tag_names):
        """Build a fake GitHub Releases API response payload."""
        return [{"tag_name": t, "draft": False} for t in tag_names]

    def _patch_urlopen(self, payload):
        """Return a urlopen patcher that yields the payload."""
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda *a: False
        # urlopen returns a ctx manager; the command calls json.load(resp)
        # which calls resp.read(). Wrap as needed.
        return patch(
            "apps.engine_rules.management.commands.sync_engine_rules"
            ".urllib.request.urlopen",
            return_value=resp,
        )

    def test_picks_highest_semver(self):
        cmd = Command()
        payload = self._mock_releases([
            "engine-rules-v0.1.0",
            "engine-rules-v0.3.0",
            "engine-rules-v0.2.5",
        ])
        with self._patch_urlopen(payload):
            tag = cmd._resolve_latest_release_tag()
        self.assertEqual(tag, "engine-rules-v0.3.0")

    def test_double_digit_minor_handled(self):
        """0.10.0 > 0.9.0 (lexical sort would lose this)."""
        cmd = Command()
        payload = self._mock_releases([
            "engine-rules-v0.9.0",
            "engine-rules-v0.10.0",
        ])
        with self._patch_urlopen(payload):
            tag = cmd._resolve_latest_release_tag()
        self.assertEqual(tag, "engine-rules-v0.10.0")

    def test_filters_non_engine_rules_tags(self):
        cmd = Command()
        payload = self._mock_releases([
            "v1.0.0",  # plugin app release, not engine-rules
            "engine-rules-v0.1.0",
            "voicings-v0.1.0",
        ])
        with self._patch_urlopen(payload):
            tag = cmd._resolve_latest_release_tag()
        self.assertEqual(tag, "engine-rules-v0.1.0")

    def test_empty_releases_raises(self):
        from django.core.management.base import CommandError
        cmd = Command()
        with self._patch_urlopen([]):
            with self.assertRaises(CommandError):
                cmd._resolve_latest_release_tag()

    def test_no_engine_rules_releases_raises(self):
        from django.core.management.base import CommandError
        cmd = Command()
        payload = self._mock_releases(["v1.0.0", "voicings-v0.1.0"])
        with self._patch_urlopen(payload):
            with self.assertRaises(CommandError):
                cmd._resolve_latest_release_tag()
