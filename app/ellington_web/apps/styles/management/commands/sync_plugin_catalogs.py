"""Sync Ellington's Style / Idiom / (optionally) Master rows from the
plugin's published catalog files.

Plugin agent (siege-analytics/musescore4-chord-library-plugin) authors
``styles.json`` + ``idioms.json`` + ``masters.json`` under
``plugin/data/`` of that repo. Each catalog ships with
``schemaVersion: "v1"`` at the top level; the loader gates on this and
refuses incompatible major versions.

Field mapping
=============

Plugin fields not present in the Ellington model — ``prescriptive_lessons``,
``example_masters``, ``diagnostic_examples``, ``compatible_styles``,
``characteristic_voicing_density``, ``characteristic_rhythmic_role``, etc. —
are captured wholesale in the new ``extra`` JSONField so consumers can
read them via the row's ``.extra`` accessor without us having to migrate
every time the plugin schema grows.

| plugin field                       | Ellington field                |
|------------------------------------|--------------------------------|
| id                                 | slug                           |
| name                               | name                           |
| summary OR description             | description                    |
| voicing_style_tag_affinity         | voicing_style_tag_affinity     |
| rhythmic_signature                 | rhythmic_signature             |
| harmonic_signature                 | harmonic_signature             |
| divergence_notes                   | divergence_notes               |
| (everything else)                  | extra (JSONField, dict)        |

Mode
====

Default: ``upsert`` — update_or_create by slug, ``is_placeholder=False``,
``schema_version=v1``. Preserves seeded-only rows the plugin hasn't
shipped yet (e.g. seeded ``modal`` while plugin's ``modal-jazz`` is
shipping — those are separate slugs).

The command does NOT delete rows. Plugin-side deletions are rare and
need operator review; deletion happens manually.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.styles.models import Idiom, Master, Style, StylePreset


# ---------------------------------------------------------------------------
# Field-mapping helpers — exported for testability
# ---------------------------------------------------------------------------


COMPARATOR_FIELDS_STYLE = {
    "voicing_style_tag_affinity",
    "rhythmic_signature",
    "harmonic_signature",
    "divergence_notes",
}

# Plugin uses ``id`` where we use ``slug``; ``summary`` where we have
# ``description``. The set below is "things we explicitly map" — all
# other plugin fields land in ``extra``.
MAPPED_STYLE_FIELDS = COMPARATOR_FIELDS_STYLE | {"id", "name", "summary", "description"}
MAPPED_IDIOM_FIELDS = {"id", "name", "summary", "description"}
MAPPED_MASTER_FIELDS = {"id", "name", "summary", "description"}


def _split_entry(entry: dict, mapped: set[str]) -> tuple[dict, dict]:
    """Partition an entry dict into mapped fields and 'everything else'.
    The 'everything else' goes into the row's ``extra`` JSONField.
    """
    plain = {k: v for k, v in entry.items() if k in mapped}
    extra = {k: v for k, v in entry.items() if k not in mapped}
    return plain, extra


def _description_for(entry: dict) -> str:
    """Plugin styles use 'summary'; idioms use 'description'. Take whichever exists."""
    return entry.get("description") or entry.get("summary") or ""


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = (
        "Sync Style / Idiom / Master rows from the plugin's published "
        "catalogs (styles.json, idioms.json, masters.json under "
        "plugin/data/). Validates schemaVersion=v1; upserts by slug; "
        "flips is_placeholder=False on imported rows. Idempotent; safe "
        "to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--plugin-data-dir",
            type=str,
            required=True,
            help=(
                "Path to the plugin's data/ directory. Must contain "
                "styles.json and idioms.json (masters.json optional)."
            ),
        )
        parser.add_argument(
            "--skip-masters",
            action="store_true",
            help="Don't import masters.json even if present (large file).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        plugin_data_dir = Path(options["plugin_data_dir"])
        if not plugin_data_dir.is_dir():
            raise CommandError(f"plugin-data-dir does not exist: {plugin_data_dir}")

        styles_imported = self._sync_styles(plugin_data_dir / "styles.json")
        idioms_imported = self._sync_idioms(plugin_data_dir / "idioms.json")

        masters_imported = 0
        if not options.get("skip_masters"):
            masters_path = plugin_data_dir / "masters.json"
            if masters_path.is_file():
                masters_imported = self._sync_masters(masters_path)
            else:
                self.stdout.write(self.style.WARNING(
                    "  masters.json not found at the configured path — skipped."
                ))

        self.stdout.write(self.style.SUCCESS(
            f"sync_plugin_catalogs: {styles_imported} styles, "
            f"{idioms_imported} idioms, {masters_imported} masters imported "
            f"(is_placeholder=False)."
        ))

    # ---- per-catalog -----------------------------------------------------

    def _sync_styles(self, path: Path) -> int:
        doc = self._load_and_validate(path, "v1")
        entries: list[dict] = doc.get("styles") or []
        if not entries:
            self.stdout.write(self.style.WARNING(
                f"  styles.json has no entries — nothing to import."
            ))
            return 0

        count = 0
        for entry in entries:
            slug = entry.get("id")
            if not slug:
                self.stdout.write(self.style.WARNING(
                    f"  styles.json entry missing 'id' — skipped: {entry.get('name')!r}"
                ))
                continue
            plain, extra = _split_entry(entry, MAPPED_STYLE_FIELDS)
            Style.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": plain.get("name") or slug,
                    "description": _description_for(plain),
                    "voicing_style_tag_affinity": entry.get("voicing_style_tag_affinity") or {},
                    "rhythmic_signature": entry.get("rhythmic_signature") or {},
                    "harmonic_signature": entry.get("harmonic_signature") or {},
                    "divergence_notes": entry.get("divergence_notes") or [],
                    "extra": extra,
                    "is_placeholder": False,
                    "schema_version": "v1",
                },
            )
            count += 1
        return count

    def _sync_idioms(self, path: Path) -> int:
        doc = self._load_and_validate(path, "v1")
        entries: list[dict] = doc.get("idioms") or []
        if not entries:
            self.stdout.write(self.style.WARNING(
                f"  idioms.json has no entries — nothing to import."
            ))
            return 0

        count = 0
        for entry in entries:
            slug = entry.get("id")
            if not slug:
                self.stdout.write(self.style.WARNING(
                    f"  idioms.json entry missing 'id' — skipped: {entry.get('name')!r}"
                ))
                continue
            plain, extra = _split_entry(entry, MAPPED_IDIOM_FIELDS)
            Idiom.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": plain.get("name") or slug,
                    "description": _description_for(plain),
                    # All non-id/name/description fields land in `extra` for idioms today —
                    # we don't have dedicated columns yet for prescriptive_lessons / etc.
                    "performance_context_metadata": {
                        k: v for k, v in entry.items()
                        if k in {
                            "characteristic_voicing_density",
                            "characteristic_rhythmic_role",
                            "compatible_styles",
                        }
                    },
                    "extra": extra,
                    "is_placeholder": False,
                    "schema_version": "v1",
                },
            )
            count += 1
        return count

    def _sync_masters(self, path: Path) -> int:
        doc = self._load_and_validate(path, "v1", required=False)
        # masters.json may not have schemaVersion gating yet — be lenient.
        entries: list[dict] | dict = doc.get("masters") or {}
        if isinstance(entries, dict):
            # masters.json sometimes ships as a dict keyed by id.
            entries = [{"id": k, **(v or {})} for k, v in entries.items()]
        if not entries:
            self.stdout.write(self.style.WARNING(
                f"  masters.json has no entries — nothing to import."
            ))
            return 0

        count = 0
        for entry in entries:
            slug = entry.get("id")
            if not slug:
                continue
            plain, extra = _split_entry(entry, MAPPED_MASTER_FIELDS)
            master, _master_created = Master.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": plain.get("name") or slug,
                    "summary": _description_for(plain),
                    "extra": extra,
                    "is_placeholder": False,
                    "schema_version": "v1",
                },
            )
            # Per coordination with the plugin agent (Ellington-side issue
            # #54): every imported Master gets a default StylePreset whose
            # slug == master.slug, so the master is immediately discoverable
            # in user-facing pickers. Curated bespoke presets (different
            # slug — e.g. "joe-pass-bebop-comping") are untouched; their
            # uniqueness on slug is what protects them.
            StylePreset.objects.update_or_create(
                slug=master.slug,
                defaults={
                    "display_name": master.name,
                    "master": master,
                },
            )
            count += 1
        return count

    # ---- shared helpers --------------------------------------------------

    def _load_and_validate(
        self, path: Path, expected_major: str, *, required: bool = True,
    ) -> dict:
        if not path.is_file():
            if required:
                raise CommandError(f"required catalog not found: {path}")
            return {}
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"{path} is not valid JSON: {exc}")
        if not isinstance(doc, dict):
            raise CommandError(f"{path} top-level must be an object, got {type(doc).__name__}")
        version = doc.get("schemaVersion")
        if required and version != expected_major:
            raise CommandError(
                f"{path} schemaVersion={version!r}, loader expects {expected_major!r}. "
                f"Bump the loader before importing."
            )
        return doc
