"""Storage helper for rendered backing-track WAVs (#235).

Mirror of ``apps.practice.storage`` for the ``backings/`` subdir.
Content-addressed by sha256, idempotent on identical bytes, with a
traversal guard on the consumer surface.

Future swap to S3-compatible object storage changes only this
module; ``BackingTrack.audio_ref`` stays an opaque string.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


_BACKINGS_SUBDIR = "backings"


@dataclass(frozen=True)
class StoredBacking:
    file_ref: str
    sha256: str
    size_bytes: int


def store_rendered_backing(src_path: Path) -> StoredBacking:
    """Move a freshly-rendered WAV into the content-addressed store.

    The caller renders to a temp WAV (typically inside a ``with
    tempfile.TemporaryDirectory()`` block from the Celery task);
    this helper hashes that file, computes the final path, and
    moves it into place atomically. Idempotent: if a backing with
    the same sha256 already exists at the destination, the source
    is removed and the existing target's file_ref is returned.
    """
    base_dir = Path(settings.MEDIA_ROOT) / _BACKINGS_SUBDIR
    base_dir.mkdir(parents=True, exist_ok=True)

    hasher = hashlib.sha256()
    size = 0
    with src_path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(64 * 1024), b""):
            hasher.update(chunk)
            size += len(chunk)
    digest = hasher.hexdigest()
    dest = base_dir / f"{digest}.wav"

    if dest.exists():
        src_path.unlink(missing_ok=True)
    else:
        # shutil.move handles cross-filesystem case if the temp dir
        # is on a different mount than MEDIA_ROOT
        shutil.move(str(src_path), str(dest))

    return StoredBacking(
        file_ref=f"{_BACKINGS_SUBDIR}/{digest}.wav",
        sha256=digest,
        size_bytes=size,
    )


def absolute_path_for(file_ref: str) -> Path:
    """Resolve a BackingTrack.audio_ref to an absolute filesystem path.

    Same traversal-guard contract as ``apps.practice.storage``: the
    resolved path must live inside ``MEDIA_ROOT``. Raises ValueError
    for any input whose normalized form escapes the media root.
    """
    base = Path(settings.MEDIA_ROOT).resolve()
    candidate = (base / file_ref).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"file_ref escapes MEDIA_ROOT: {file_ref!r}")
    return candidate
