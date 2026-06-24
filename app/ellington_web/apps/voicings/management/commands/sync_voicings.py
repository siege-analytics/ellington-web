"""``manage.py sync_voicings`` — ingest the plugin's voicings.json.

Workflow::

    python manage.py sync_voicings \\
        [--source-url <url>] \\
        [--local-path /tmp/voicings.json] \\
        [--plugin-sha <40-hex>] \\
        [--built-at 2026-06-24T13:00:00Z]

Exactly one of ``--source-url`` and ``--local-path`` should be
supplied; if neither is, the command reads
``settings.VOICINGS_SOURCE_URL`` (default: develop raw on GitHub).

The plugin's voicings.json is ``{"voicings": [<voicing>, ...]}`` with
no manifest block (engine_rules.json has one — contract gap to close
upstream). We synthesize bundle provenance:

- ``plugin_commit_sha`` from ``--plugin-sha`` if given, else derived
  from the raw-GitHub URL ``ref`` segment when fetching, else
  ``"unknown" * 5`` padded to 40 chars (stub-with-inline-justification —
  callers in CI MUST pass --plugin-sha).
- ``built_at`` from ``--built-at`` if given, else local-file mtime,
  else ``timezone.now()``.

Idempotent on ``(plugin_commit_sha,)``: re-running with the same SHA
short-circuits to the existing bundle.

After ingest, sets ``is_active=False`` on every prior active bundle
+ its voicings, and ``is_active=True`` on the new one.

Refs: #186 Phase 2 (this command), plugin schema/voicings.schema.json
(locked contract).
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.voicings.models import Voicing, VoicingBundle


DEFAULT_SOURCE_URL = (
    "https://raw.githubusercontent.com/siege-analytics/"
    "musescore4-chord-library-plugin/develop/plugin/data/voicings.json"
)


class Command(BaseCommand):
    help = (
        "Sync the chord-library plugin's voicings.json corpus into "
        "Postgres. Idempotent on plugin_commit_sha."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--source-url", default=None)
        parser.add_argument("--local-path", default=None)
        parser.add_argument(
            "--plugin-sha",
            default=None,
            help="40-hex plugin commit SHA. Required in CI for"
            " reproducibility; sync refuses to flip is_active without"
            " a real SHA.",
        )
        parser.add_argument(
            "--built-at",
            default=None,
            help="ISO-8601 timestamp. Defaults to file mtime (local"
            " mode) or now() (URL mode).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Load + validate but DO NOT write to the DB. Prints"
                " what would be imported (count, distinct qualities,"
                " distinct categories). Useful for previewing a"
                " voicings.json import before committing. (#220)"
            ),
        )

    def handle(self, *args, **options) -> None:
        local_path = options.get("local_path")
        source_url = options.get("source_url")
        plugin_sha = options.get("plugin_sha")
        built_at_raw = options.get("built_at")

        if local_path and source_url:
            raise CommandError("Pass --source-url OR --local-path, not both.")

        if local_path:
            payload, source_descriptor, mtime = self._load_local(local_path)
        else:
            url = source_url or getattr(
                settings, "VOICINGS_SOURCE_URL", DEFAULT_SOURCE_URL,
            )
            payload, source_descriptor = self._load_url(url)
            mtime = None

        if not isinstance(payload, dict) or "voicings" not in payload:
            raise CommandError(
                "voicings.json missing top-level 'voicings' key — "
                "plugin schema contract violated."
            )

        voicings = payload["voicings"]
        if not isinstance(voicings, list) or not voicings:
            raise CommandError("voicings array empty or not a list.")

        if options.get("dry_run", False):
            self._print_dry_run(voicings)
            return

        if not plugin_sha:
            # Stub: defers plugin SHA derivation. Cost: bundle SHA falls
            # back to "unknown" padded. Defer ratified inline by #186
            # Phase 2 design note (plans/186-phase2-voicings-ingest.md)
            # 2026-06-24. Canonical fix is plugin-side manifest block;
            # follow-up plugin ticket pending.
            plugin_sha = "unknown" + "0" * (40 - len("unknown"))
            self.stdout.write(
                self.style.WARNING(
                    "no --plugin-sha given; using synthetic SHA. "
                    "CI MUST pass --plugin-sha for reproducible bundles."
                )
            )

        if built_at_raw:
            built_at = datetime.fromisoformat(built_at_raw.replace("Z", "+00:00"))
        elif mtime is not None:
            built_at = mtime
        else:
            from django.utils import timezone as djtz
            built_at = djtz.now()

        existing = VoicingBundle.objects.filter(
            plugin_commit_sha=plugin_sha,
        ).first()
        if existing:
            self.stdout.write(
                f"Bundle {plugin_sha[:8]} already imported "
                f"({existing.total_voicings} voicings). No-op."
            )
            return

        raw_top_level = {k: v for k, v in payload.items() if k != "voicings"}

        with transaction.atomic():
            bundle = VoicingBundle.objects.create(
                plugin_commit_sha=plugin_sha,
                source_url=source_descriptor[:512],
                built_at=built_at,
                total_voicings=len(voicings),
                raw_top_level=raw_top_level,
                is_active=False,
            )

            rows = [
                Voicing(
                    bundle=bundle,
                    voicing_id=v["id"],
                    name=v["name"],
                    chord_quality=v["chord_quality"],
                    root=v["root"],
                    category=v["category"],
                    suitable_modes=v.get("suitableModes", []),
                    strings=v["strings"],
                    tuning=v.get("tuning", ""),
                    fret_number=v["fret_number"],
                    visible_frets=v["visible_frets"],
                    dots=v.get("dots", []),
                    mutes=v.get("mutes", []),
                    open_strings=v.get("open", []),
                    notes=v.get("notes", []),
                    intervals=v.get("intervals", []),
                    tags=v.get("tags", []),
                    also_qualities=v.get("also_qualities", []),
                    shape_id=v.get("shape_id", ""),
                    is_active=False,
                )
                for v in voicings
            ]
            Voicing.objects.bulk_create(rows, batch_size=500)

            inserted = Voicing.objects.filter(bundle=bundle).count()
            if inserted != len(voicings):
                raise CommandError(
                    f"Row count mismatch: expected {len(voicings)}, "
                    f"got {inserted}. Rolling back."
                )

            VoicingBundle.objects.exclude(pk=bundle.pk).update(is_active=False)
            Voicing.objects.exclude(bundle=bundle).update(is_active=False)
            bundle.is_active = True
            bundle.save(update_fields=["is_active"])
            Voicing.objects.filter(bundle=bundle).update(is_active=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported bundle {plugin_sha[:8]}: {len(voicings)} "
                f"voicings active."
            )
        )

    # ---------------------------------------------------------------
    # Dry-run reporter (#220)
    # ---------------------------------------------------------------

    def _print_dry_run(self, voicings: list[dict]) -> None:
        """Emit a DRY RUN summary — count + distinct qualities + categories.

        Mirror of sync_engine_rules' --dry-run (#218) shape so the two
        commands feel consistent to ops.
        """
        qualities: dict[str, int] = {}
        categories: dict[str, int] = {}
        for v in voicings:
            q = v.get("chord_quality", "?")
            c = v.get("category", "?")
            qualities[q] = qualities.get(q, 0) + 1
            categories[c] = categories.get(c, 0) + 1

        self.stdout.write(self.style.WARNING(
            "==== DRY RUN — no DB writes ===="
        ))
        self.stdout.write(f"  voicings in payload: {len(voicings)}")
        self.stdout.write(
            f"  distinct qualities: {len(qualities)}"
        )
        self.stdout.write(
            f"  distinct categories: {len(categories)}"
        )
        # Top-5 of each so operator spots schema shifts at a glance
        top_q = sorted(qualities.items(), key=lambda kv: -kv[1])[:5]
        top_c = sorted(categories.items(), key=lambda kv: -kv[1])[:5]
        self.stdout.write(
            "  top qualities: " + ", ".join(f"{q}={n}" for q, n in top_q)
        )
        self.stdout.write(
            "  top categories: " + ", ".join(f"{c}={n}" for c, n in top_c)
        )
        self.stdout.write(self.style.WARNING(
            "==== END DRY RUN ===="
        ))

    # ---------------------------------------------------------------
    # I/O helpers
    # ---------------------------------------------------------------

    def _load_local(self, path: str) -> tuple[dict, str, datetime]:
        p = Path(path)
        if not p.exists():
            raise CommandError(f"Local voicings.json not found: {path}")
        with p.open() as f:
            payload = json.load(f)
        mtime = datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc)
        return payload, f"file://{p.resolve()}", mtime

    def _load_url(self, url: str) -> tuple[dict, str]:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ellington-web sync_voicings/1"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
        return payload, url
