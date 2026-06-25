"""``manage.py scan_sound_banks`` — discover SoundFont / DLS banks on disk.

Per epic #232 / child #233. Walks configured paths, computes sha256
of each candidate file, and ``update_or_create``-s a ``SoundBank``
row keyed on the hash. Re-running on the same machine is a no-op.

Configuration:
- ``settings.SOUND_BANK_PATHS`` — list of (path, source_app) tuples
- Env override: ``ELLINGTON_SOUND_BANK_PATHS`` — ``:``-separated
  absolute paths; all treated as ``source_app=other``

Defaults (macOS dev) — env-overridable per #232:

- ``/Applications/MuseScore 4.app/Contents/Resources/sound/`` → musescore
- ``~/Documents/MuseScore4/Soundfonts/`` → user
- ``/Library/Audio/Sounds/Banks/`` → system

Production (Linux): set the env override to the worker image's bank
mount point.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.audio.models import BankFormat, BankSourceApp, SoundBank


BANK_EXTENSIONS = {".sf2": BankFormat.SF2, ".sf3": BankFormat.SF3, ".dls": BankFormat.DLS}


DEFAULT_SCAN_TARGETS = [
    ("/Applications/MuseScore 4.app/Contents/Resources/sound", BankSourceApp.MUSESCORE),
    ("~/Documents/MuseScore4/Soundfonts", BankSourceApp.USER),
    ("/Library/Audio/Sounds/Banks", BankSourceApp.SYSTEM),
]


class Command(BaseCommand):
    help = (
        "Discover SoundFont/DLS banks on disk and register them as "
        "SoundBank rows. Idempotent on file sha256."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--path",
            action="append",
            default=[],
            help="Additional directory to scan. Repeatable. All paths"
            " supplied via --path are tagged source_app=other.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Discover + hash but skip DB writes. Reports what"
            " would be added vs. already-known.",
        )

    def handle(self, *args, **options) -> None:
        targets = self._collect_targets(options.get("path") or [])

        new_count = 0
        existing_count = 0
        dry_run = options.get("dry_run", False)
        for path_str, source in targets:
            for bank in self._walk(path_str):
                fmt = BANK_EXTENSIONS[bank.suffix.lower()]
                sha = self._hash(bank)
                size = bank.stat().st_size

                if dry_run:
                    seen = SoundBank.objects.filter(sha256=sha).first()
                    if seen:
                        existing_count += 1
                    else:
                        new_count += 1
                    continue

                _, created = SoundBank.objects.update_or_create(
                    sha256=sha,
                    defaults={
                        "source_app": source,
                        "name": bank.name,
                        "format": fmt,
                        "path": str(bank),
                        "size_bytes": size,
                    },
                )
                if created:
                    new_count += 1
                else:
                    existing_count += 1

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}scan_sound_banks: {new_count} new, "
            f"{existing_count} already known."
        ))

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    def _collect_targets(self, cli_paths: list[str]) -> list[tuple[str, str]]:
        """Build the (path, source_app) target list from settings + env + CLI."""
        targets: list[tuple[str, str]] = []

        targets.extend(getattr(settings, "SOUND_BANK_PATHS", DEFAULT_SCAN_TARGETS))

        env_paths = os.environ.get("ELLINGTON_SOUND_BANK_PATHS") or ""
        for p in env_paths.split(":"):
            p = p.strip()
            if p:
                targets.append((p, BankSourceApp.OTHER))

        for p in cli_paths:
            targets.append((p, BankSourceApp.OTHER))

        return targets

    def _walk(self, path_str: str) -> Iterable[Path]:
        path = Path(path_str).expanduser()
        if not path.is_dir():
            return
        for f in path.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() in BANK_EXTENSIONS:
                yield f

    def _hash(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fp:
            for chunk in iter(lambda: fp.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
