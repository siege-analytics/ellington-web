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
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from django.conf import settings


_RECORDINGS_SUBDIR = "recordings"
_CHUNK_SIZE = 64 * 1024  # 64KB — balances RAM use vs syscall overhead

# Allowed audio extensions, shared by ``forms.PracticeSessionForm`` (which
# rejects uploads at the boundary) and by ``_extension_from_name`` below
# (which strips unknown extensions as defense-in-depth). Keep this list
# the single source of truth so the two layers don't drift.
ALLOWED_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".wav", ".mp3", ".m4a", ".flac", ".aiff", ".ogg"}
)


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

    # Write to an OS-allocated temp path first, hash as we go, then
    # atomic-rename to the content-addressed final name. Using
    # ``tempfile.NamedTemporaryFile`` (rather than ``id(uploaded_file)``)
    # gives us a unique name even when multiple processes (e.g. a future
    # Celery worker pool) call store_upload concurrently — ``id()`` is
    # only unique within one interpreter process.
    tmp_fd, tmp_str = tempfile.mkstemp(prefix=".partial-", dir=str(base_dir))
    tmp_path = Path(tmp_str)
    hasher = hashlib.sha256()
    size = 0
    try:
        with open(tmp_fd, "wb") as out:
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
    """Resolve a Recording.file_ref to an absolute filesystem path.

    Guards against path-traversal: the resolved path must live inside
    ``MEDIA_ROOT``. Raises ``ValueError`` for inputs like
    ``"../../etc/passwd"`` or any string whose normalized form escapes
    the media root, even when supplied via a future Celery worker or a
    bypass-the-form code path. ``store_upload`` produces safe refs by
    construction (``recordings/<sha256>.<ext>``); this check defends the
    *consumer* surface, not the producer.
    """
    base = Path(settings.MEDIA_ROOT).resolve()
    candidate = (base / file_ref).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(
            f"file_ref escapes MEDIA_ROOT: {file_ref!r}"
        )
    return candidate


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
    # Only allow the small whitelist of audio extensions; everything
    # else gets stored without an extension. The form layer should
    # already reject unsupported types, but this is defense in depth.
    if ext in ALLOWED_AUDIO_EXTENSIONS:
        return ext
    return ""


__all__ = [
    "ALLOWED_AUDIO_EXTENSIONS",
    "StoredFile",
    "absolute_path_for",
    "store_upload",
]
