"""File storage helper for practice Recordings.

Content-addressed local storage under ``MEDIA_ROOT/recordings/``. The
file's SHA-256 digest is the canonical name; this gives us free
deduplication (two users uploading the same bounce share one blob) and
makes ``Recording.file_ref`` opaque + stable across rename/move.

For v0 we write to the pod's mounted PVC. Swapping to S3-compatible
object storage later is a matter of changing this module's
``store_upload`` implementation; ``Recording.file_ref`` stays a string,
no schema migration needed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from django.conf import settings


_RECORDINGS_SUBDIR = "recordings"
_CHUNK_SIZE = 64 * 1024  # 64KB — balances RAM use vs syscall overhead


@dataclass(frozen=True)
class StoredFile:
    """Result of writing one upload to the storage layer."""

    file_ref: str
    """Opaque reference for ``Recording.file_ref`` — relative path
    starting with ``recordings/``. Joining with ``MEDIA_ROOT`` gives the
    absolute path."""

    sha256: str
    """Hex digest. Same value as the basename of ``file_ref`` (the
    extension reflects the upload's original format)."""

    size_bytes: int

    extension: str
    """Lower-cased extension from the original upload, including the
    leading dot (e.g. '.wav'). Empty string when none."""


def store_upload(uploaded_file: IO[bytes], original_name: str) -> StoredFile:
    """Stream the upload to disk under MEDIA_ROOT, hashing as we go.

    Returns a :class:`StoredFile` whose ``file_ref`` is suitable for
    ``Recording.file_ref``. Idempotent: re-uploading the same file
    produces the same ``file_ref`` and overwrites identical content (no
    duplicate blobs).

    The caller is responsible for the Django ``UploadedFile`` flow
    (form validation, content-type checks). This module is intentionally
    Django-agnostic at the file-level so the same helper could be
    invoked from a Celery worker later if uploads move async.
    """
    extension = _extension_from_name(original_name)
    base_dir = Path(settings.MEDIA_ROOT) / _RECORDINGS_SUBDIR
    base_dir.mkdir(parents=True, exist_ok=True)

    # Write to a temp path first, hash as we go, then rename to the
    # content-addressed final name. This avoids partial-write races on
    # the final path.
    tmp_path = base_dir / f".partial-{id(uploaded_file)}"
    hasher = hashlib.sha256()
    size = 0
    try:
        with tmp_path.open("wb") as out:
            for chunk in _iter_chunks(uploaded_file):
                hasher.update(chunk)
                out.write(chunk)
                size += len(chunk)
        digest = hasher.hexdigest()
        final_path = base_dir / f"{digest}{extension}"
        # If the destination already exists, prefer it over the new write
        # (idempotency). Else atomic rename.
        if final_path.exists():
            tmp_path.unlink()
        else:
            tmp_path.replace(final_path)
        return StoredFile(
            file_ref=f"{_RECORDINGS_SUBDIR}/{digest}{extension}",
            sha256=digest,
            size_bytes=size,
            extension=extension,
        )
    except Exception:
        # Clean up the partial file on any failure
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def absolute_path_for(file_ref: str) -> Path:
    """Resolve a Recording.file_ref to an absolute filesystem path."""
    return Path(settings.MEDIA_ROOT) / file_ref


def _iter_chunks(uploaded_file: IO[bytes]):
    """Read chunks from an UploadedFile-like object."""
    # Django's UploadedFile has a `chunks()` method; fall back to read()
    # for plain file-likes (used in tests + future Celery flow).
    chunks_method = getattr(uploaded_file, "chunks", None)
    if callable(chunks_method):
        yield from chunks_method(chunk_size=_CHUNK_SIZE)
        return
    while True:
        chunk = uploaded_file.read(_CHUNK_SIZE)
        if not chunk:
            break
        yield chunk


def _extension_from_name(name: str) -> str:
    """Return the lower-cased extension including the dot, or empty string.

    Strips the path components defensively — a malicious upload name
    like ``../../etc/passwd`` becomes ``passwd`` then yields ``''``.
    """
    if not name:
        return ""
    base = Path(name).name  # strips any directory components
    if "." not in base:
        return ""
    ext = "." + base.rsplit(".", 1)[1].lower()
    # Only allow a small whitelist of audio extensions; everything else
    # gets stored without an extension. The form layer should already
    # reject unsupported types, but this is defense in depth.
    if ext in {".wav", ".mp3", ".m4a", ".flac", ".aiff", ".ogg"}:
        return ext
    return ""


__all__ = ["StoredFile", "absolute_path_for", "store_upload"]
