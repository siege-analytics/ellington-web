"""``manage.py sync_engine_rules`` — pull a pinned plugin Release bundle
and upsert the EngineRule catalog.

Workflow::

    python manage.py sync_engine_rules \\
        [--release-tag engine-rules-v0.1.0] \\
        [--bundle-path /tmp/engine-rules-bundle.tar.gz]

Exactly one of ``--release-tag`` and ``--bundle-path`` should be
supplied; if neither is, the command reads
``settings.ENGINE_RULES_RELEASE_TAG``. ``--bundle-path`` is the local-
disk hook for offline testing — the orchestrator never reaches for
the network.

The bundle layout (per firing-spec v0.1) is::

    engine-rules-bundle.tar.gz
    ├── manifest.json
    └── masters/
        └── <master_id>/
            └── <work_id>/
                └── derived/
                    └── engine-rules.json    # list of rules

Each engine-rules.json is a dict with key ``rules`` whose value is the
list of per-rule dicts to upsert.

Upsert key is ``(bundle, master, work_id, rule_id)``. Re-running with
the same tag is a no-op (bundle's unique constraint matches; rules
are upserted in place but their content shouldn't change).

After the bundle is imported, the command marks every previously-active
rule whose key is NOT present in the new bundle as ``is_active=False``.
Historical RuleFire→EngineRule joins keep working — the EngineRule row
survives, just stops appearing in firing queries.

Refs: #97 (this ticket), plugin #549 (firing semantics spec),
plugin release pipeline #548.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.engine_rules.models import EngineRule, EngineRulesBundle
from apps.styles.models import Master


# Our consumer-side declared version. When the manifest's
# ``min_consumer_version`` is greater than this, the sync refuses to
# proceed — operator must upgrade Ellington first.
CONSUMER_VERSION = "0.2.0"

# GitHub Release URL template for the plugin's engine-rules releases.
# The release tag is the input; the asset name is fixed per the
# release-pipeline convention agreed with the plugin agent.
RELEASE_URL_TEMPLATE = (
    "https://github.com/siege-analytics/musescore4-chord-library-plugin"
    "/releases/download/{tag}/engine-rules-bundle.tar.gz"
)

# Plugin firing-spec v0.1 §2 alias table. Maps legacy
# ``quality_binding`` notation to canonical chord-quality tokens during
# the transition window until plugin #555 lands the corpus migration.
# Canonical token set per spec: maj7, dom7, min7, min7b5, dim7, maj6,
# min6, sus2, sus4, alt7, any. Bundles built after #555 are
# pre-normalized; this fallback then runs as a no-op.
#
# Corrected vs first draft after plugin hostile review (PR #99):
#   * min7 was kept (canonical), NOT mapped to "m7" (not canonical)
#   * maj7 -> maj7 no-op removed
#   * minor/major mappings dropped — those reference the v0.2
#     family-parent spec being drafted on plugin #555, not v0.1.
QUALITY_ALIAS = {
    "seventh": "dom7",
    "7": "dom7",
    "dominant7": "dom7",
    "dominant_7": "dom7",
    "major7": "maj7",
    "minor7": "min7",
    "half-diminished": "min7b5",
    "diminished": "dim7",
}


class Command(BaseCommand):
    help = (
        "Pull a pinned engine-rules release from the chord-library "
        "plugin's GitHub Releases, validate the manifest, and upsert "
        "EngineRule rows into Postgres. Idempotent."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--release-tag",
            default=None,
            help=(
                "Plugin release tag to pull (e.g. 'engine-rules-v0.1.0')."
                " Falls back to settings.ENGINE_RULES_RELEASE_TAG."
            ),
        )
        parser.add_argument(
            "--bundle-path",
            default=None,
            help=(
                "Path to a local engine-rules-bundle.tar.gz. When set,"
                " skips the network and reads the tarball from disk."
                " Useful for offline tests."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Override the safety guard that refuses a sync where"
                " the new bundle contains fewer than 50%% of the"
                " previously-active rules. Use only when the corpus"
                " has legitimately shrunk (e.g. a re-organization)."
            ),
        )

    def handle(self, *args, **options) -> None:
        release_tag = options.get("release_tag") or getattr(
            settings, "ENGINE_RULES_RELEASE_TAG", None
        )
        bundle_path = options.get("bundle_path")

        if not release_tag and not bundle_path:
            raise CommandError(
                "no release tag set: pass --release-tag, --bundle-path,"
                " or set settings.ENGINE_RULES_RELEASE_TAG"
            )

        with _open_bundle(bundle_path, release_tag) as tar:
            manifest = _load_manifest(tar)
            self._validate_manifest(manifest)
            rules_by_path = _load_rules_files(tar)

        bundle = self._upsert_bundle(manifest)
        prior_active_pks = set(
            EngineRule.objects.filter(is_active=True).values_list("pk", flat=True)
        )
        upserted_pks = self._upsert_rules(bundle, manifest, rules_by_path)
        # Sanity guard — refuse a sync that would deactivate more
        # than 50% of prior-active rules unless --force. Catches the
        # accidental empty-bundle scenario; legitimate large corpus
        # restructures still possible with explicit override.
        # Plugin agent Q3 ask on PR #99.
        self._guard_against_mass_deactivation(
            prior_active_pks, upserted_pks, force=options.get("force", False)
        )
        deactivated = self._deactivate_missing(prior_active_pks, upserted_pks)

        self.stdout.write(
            self.style.SUCCESS(
                f"sync_engine_rules: bundle={bundle.bundle_version} "
                f"({bundle.plugin_commit_sha[:8]}) imported "
                f"{len(upserted_pks)} rules across {len(rules_by_path)} files; "
                f"deactivated {deactivated} stale rules."
            )
        )

    # ---- validation -----------------------------------------------------

    def _validate_manifest(self, manifest: dict[str, Any]) -> None:
        """Refuse bundles whose min_consumer_version exceeds ours."""
        min_consumer = manifest.get("min_consumer_version")
        if min_consumer and _semver_gt(min_consumer, CONSUMER_VERSION):
            raise CommandError(
                f"bundle requires consumer version >= {min_consumer}; "
                f"Ellington's engine_rules consumer is {CONSUMER_VERSION}. "
                "Upgrade Ellington before syncing this bundle."
            )

    # ---- DB writes ------------------------------------------------------

    @transaction.atomic
    def _upsert_bundle(self, manifest: dict[str, Any]) -> EngineRulesBundle:
        bundle, _created = EngineRulesBundle.objects.update_or_create(
            plugin_commit_sha=manifest["plugin_commit_sha"],
            bundle_version=manifest["bundle_version"],
            defaults={
                "schema_version": manifest["schema_version"],
                "built_at": manifest["built_at"],
                "total_rules": manifest["total_rules"],
                "manifest": manifest,
            },
        )
        return bundle

    @transaction.atomic
    def _upsert_rules(
        self,
        bundle: EngineRulesBundle,
        manifest: dict[str, Any],
        rules_by_path: dict[str, dict[str, Any]],
    ) -> set[int]:
        """Upsert every rule from every (master, work) file in the bundle."""
        upserted: set[int] = set()
        # Index manifest's master rollup for O(1) lookups while parsing
        # the per-file rules.
        for path, doc in rules_by_path.items():
            master_id, work_id = _parse_rules_path(path)
            try:
                master = Master.objects.get(slug=master_id)
            except Master.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(
                        f"  skipping {path}: master '{master_id}' not in DB "
                        "(run sync_plugin_catalogs first?)"
                    )
                )
                continue

            # Plugin firing-spec v0.1 §6 mandates the rules array key
            # is "engine_rules", not "rules". The earlier "rules" key
            # in this code (and the matching test fixture) was
            # plugin-bundle-incompatible — silently zero-result on
            # real bundles. Fixed in PR #99 hostile review. The bundle
            # actually uses ``engine_rules``; ``rules`` is tolerated
            # as a legacy fallback during the transition window.
            for entry in doc.get("engine_rules", doc.get("rules", [])):
                pk = self._upsert_one_rule(bundle, master, work_id, entry)
                if pk is not None:
                    upserted.add(pk)
        return upserted

    def _upsert_one_rule(
        self,
        bundle: EngineRulesBundle,
        master: Master,
        work_id: str,
        entry: dict[str, Any],
    ) -> int | None:
        rule_id = entry.get("rule_id")
        if not rule_id:
            self.stdout.write(
                self.style.WARNING(
                    f"  skipping rule with no rule_id under {master.slug}/{work_id}"
                )
            )
            return None

        rule, _ = EngineRule.objects.update_or_create(
            bundle=bundle,
            master=master,
            work_id=work_id,
            rule_id=rule_id,
            defaults={
                "name": entry.get("name", ""),
                "preference": _coerce_preference(entry.get("preference")),
                "quality_binding": _normalize_quality_binding(
                    entry.get("quality_binding", [])
                ),
                "applicability_reasons": list(
                    entry.get("applicability_reasons", []) or []
                ),
                "when_predicate": entry.get("when", entry.get("when_predicate", {})),
                "then_action": entry.get("then", entry.get("then_action", {})),
                "falsifier": entry.get("falsifier") or "",
                "anchor": entry.get("anchor") or "",
                "source_page": entry.get("source_page"),
                "source_pdf_filename": (entry.get("pdf_filename") or "").strip(),
                "is_active": True,
            },
        )
        return rule.pk

    def _deactivate_missing(
        self, prior_active_pks: set[int], upserted_pks: set[int]
    ) -> int:
        to_deactivate = prior_active_pks - upserted_pks
        if not to_deactivate:
            return 0
        return EngineRule.objects.filter(pk__in=to_deactivate).update(
            is_active=False
        )

    def _guard_against_mass_deactivation(
        self,
        prior_active_pks: set[int],
        upserted_pks: set[int],
        *,
        force: bool,
    ) -> None:
        """Refuse sync runs that would deactivate >50% of prior rules.

        Saves operators from accidentally syncing an empty / malformed
        bundle and silently wiping the catalog. Legitimate large
        deletions (corpus restructure) override with ``--force``.

        Skip when there are no prior rules — a first-ever sync writes
        an arbitrary number with no prior to compare against.
        """
        if not prior_active_pks:
            return
        if force:
            return
        new_count = len(upserted_pks)
        prior_count = len(prior_active_pks)
        if new_count * 2 < prior_count:
            raise CommandError(
                f"sanity guard: new bundle has {new_count} rules vs "
                f"{prior_count} previously active "
                f"({new_count / prior_count:.0%}). Refusing to deactivate "
                "more than half the catalog. Re-run with --force if "
                "this is intentional (e.g. corpus restructure)."
            )


# ---------------------------------------------------------------------------
# Bundle reading helpers (module-level for testability)
# ---------------------------------------------------------------------------


@contextmanager
def _open_bundle(
    bundle_path: str | None, release_tag: str | None
) -> Iterator[tarfile.TarFile]:
    """Yield a tarfile.TarFile for the bundle, from disk or HTTPS."""
    if bundle_path:
        with tarfile.open(bundle_path, "r:gz") as tar:
            yield tar
        return
    url = RELEASE_URL_TEMPLATE.format(tag=release_tag)
    with urllib.request.urlopen(url) as resp:  # noqa: S310 — trusted GH URL
        data = resp.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        yield tar


def _load_manifest(tar: tarfile.TarFile) -> dict[str, Any]:
    """Read manifest.json from the bundle root."""
    try:
        member = tar.getmember("manifest.json")
    except KeyError as exc:
        raise CommandError(
            "bundle has no manifest.json at the root"
        ) from exc
    fp = tar.extractfile(member)
    if fp is None:
        raise CommandError("could not read manifest.json from bundle")
    return json.loads(fp.read().decode("utf-8"))


# Match either the v0.1.0 bundle layout
# (``plugin/data/masters-corpus/<master>/<work>/derived/engine-rules.json``
# — leaks plugin-internal paths; flagged by plugin agent in PR #99
# hostile review) or the cleaned-up v0.1.1+ layout
# (``masters/<master>/<work>/derived/engine-rules.json``). Plugin agent
# will ship the path-cleanup release; tolerating both keeps Ellington
# functional during the transition window.
_RULES_PATH_RE = re.compile(
    r"^(?:plugin/data/masters-corpus|masters)"
    r"/(?P<master_id>[^/]+)/(?P<work_id>[^/]+)/derived/engine-rules\.json$"
)


def _load_rules_files(tar: tarfile.TarFile) -> dict[str, dict[str, Any]]:
    """Collect every engine-rules.json file from the bundle, keyed by path."""
    out: dict[str, dict[str, Any]] = {}
    for member in tar.getmembers():
        if not _RULES_PATH_RE.match(member.name):
            continue
        fp = tar.extractfile(member)
        if fp is None:
            continue
        out[member.name] = json.loads(fp.read().decode("utf-8"))
    return out


def _parse_rules_path(path: str) -> tuple[str, str]:
    """Extract (master_id, work_id) from a bundle path."""
    m = _RULES_PATH_RE.match(path)
    if not m:
        raise CommandError(f"unexpected rules path: {path!r}")
    return m.group("master_id"), m.group("work_id")


# ---------------------------------------------------------------------------
# Value coercion helpers
# ---------------------------------------------------------------------------


def _coerce_preference(value: Any) -> int:
    """Map plugin's preference field to the signed Likert SmallIntegerField.

    The plugin emits integers in firing-spec v0.1. Legacy bundles may
    emit strings (``"required"``, ``"avoid"``, etc.); coerce best-effort
    to keep the transition window painless.
    """
    if isinstance(value, int):
        return max(-2, min(2, value))
    if isinstance(value, str):
        legacy = {
            "required": 2,
            "preferred": 1,
            "recommended": 1,
            "neutral": 0,
            "avoid": -1,
            "strong_avoid": -2,
        }
        return legacy.get(value, 0)
    return 0


def _normalize_quality_binding(value: Any) -> list[str]:
    """Apply firing-spec §2 alias table to legacy quality_binding tokens.

    Plugin #555 will land the corpus migration that pre-normalizes
    everything upstream; until then, this fallback path keeps Ellington
    consuming older bundles cleanly.
    """
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    return [QUALITY_ALIAS.get(v, v) for v in value]


# ---------------------------------------------------------------------------
# Semver comparison (no external deps — keep it dumb for two-segment vsns)
# ---------------------------------------------------------------------------


def _semver_gt(a: str, b: str) -> bool:
    """Return True if version string a > b. Three-segment major.minor.patch."""
    return _semver_tuple(a) > _semver_tuple(b)


def _semver_tuple(v: str) -> tuple[int, ...]:
    parts = v.split(".")
    return tuple(int(p) for p in parts if p.isdigit())
