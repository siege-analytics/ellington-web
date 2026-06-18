"""File storage helper for PDF lead-sheet uploads (Phase 4-PDF / #82).

Mirrors the apps.practice.storage pattern: content-addressed local
storage under ``MEDIA_ROOT/pdf_upload/``, SHA-256 as the canonical
name, idempotent re-upload. Separate module from practice.storage
because the allowed extension set differs (.pdf only) and PDF is a
charts-domain concept, not a practice-flow concept.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from django.conf import settings


_PDF_UPLOAD_SUBDIR = "pdf_upload"
_CHUNK_SIZE = 64 * 1024

ALLOWED_PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

# PDF magic bytes — the first 4 bytes of every PDF are b"%PDF". We
# sniff the head to defeat ".pdf"-renamed binaries that aren't actually
# PDFs (the omr-leadsheet pipeline would crash on those much later in
# the flow with a less actionable error).
_PDF_MAGIC = b"%PDF"


@dataclass(frozen=True)
class StoredPDF:
    """Result of writing one PDF upload to the storage layer."""

    file_ref: str
    """Opaque reference for ``ChartImport.file_ref`` — relative path
    starting with ``pdf_upload/``."""

    sha256: str
    """Hex digest. Same value as the basename of ``file_ref``."""

    size_bytes: int


def store_pdf_upload(uploaded_file: IO[bytes], original_name: str) -> StoredPDF:
    """Stream a PDF upload to disk under MEDIA_ROOT, hashing as we go.

    Idempotent: re-uploading the same content produces the same
    ``file_ref``. The caller is responsible for size + extension
    validation at the form layer; this module handles the storage flow
    + a magic-byte sniff for defense-in-depth.
    """
    base_dir = Path(settings.MEDIA_ROOT) / _PDF_UPLOAD_SUBDIR
    base_dir.mkdir(parents=True, exist_ok=True)

    tmp_fd, tmp_str = tempfile.mkstemp(prefix=".partial-", dir=str(base_dir))
    tmp_path = Path(tmp_str)
    hasher = hashlib.sha256()
    size = 0
    sniffed = False
    try:
        with open(tmp_fd, "wb") as out:
            for chunk in _iter_chunks(uploaded_file):
                if not sniffed:
                    if not chunk.startswith(_PDF_MAGIC):
                        raise ValueError(
                            "uploaded file does not look like a PDF"
                            " (missing %PDF magic bytes)"
                        )
                    sniffed = True
                hasher.update(chunk)
                out.write(chunk)
                size += len(chunk)

        if not sniffed:
            raise ValueError("uploaded file is empty")

        digest = hasher.hexdigest()
        final_path = base_dir / f"{digest}.pdf"
        if final_path.exists():
            tmp_path.unlink()
        else:
            tmp_path.replace(final_path)
        return StoredPDF(
            file_ref=f"{_PDF_UPLOAD_SUBDIR}/{digest}.pdf",
            sha256=digest,
            size_bytes=size,
        )
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def absolute_path_for_pdf(file_ref: str) -> Path:
    """Resolve a ChartImport.file_ref to an absolute path with
    traversal guard. Mirrors apps.practice.storage.absolute_path_for.
    """
    base = Path(settings.MEDIA_ROOT).resolve()
    candidate = (base / file_ref).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"file_ref escapes MEDIA_ROOT: {file_ref!r}")
    return candidate


def _iter_chunks(uploaded_file: IO[bytes]):
    chunks_method = getattr(uploaded_file, "chunks", None)
    if callable(chunks_method):
        yield from chunks_method(chunk_size=_CHUNK_SIZE)
        return
    while True:
        chunk = uploaded_file.read(_CHUNK_SIZE)
        if not chunk:
            break
        yield chunk


__all__ = [
    "ALLOWED_PDF_EXTENSIONS",
    "StoredPDF",
    "absolute_path_for_pdf",
    "store_pdf_upload",
]
