"""Celery tasks for the Phase 4-PDF OMR pipeline.

Single task here, ``process_pdf_chart``, runs one ChartImport through
omr-leadsheet (the :mod:`apps.charts.omr` wrapper) then through
:mod:`ingest.musescore` so the resulting Songs land in the
practitioner's Songbook.

Lifecycle (mirrors the Recording.analysis_status race-fix discipline
from #67/#69):

    PENDING/FAILED ──► QUEUED (set by ``dispatch_pdf_chart`` BEFORE delay)
    QUEUED         ──► RUNNING (this task on entry)
    RUNNING        ──► COMPLETE  (page succeeded, Songs imported)
                       │
                       ├──► PARTIAL   (degenerate in #81 v1 since
                       │               page_count=1; the splitter in
                       │               #84 activates this branch)
                       └──► FAILED    (orchestrator exception, or
                                       omr-leadsheet returned no .mscz)

The task layer NEVER mutates ``ChartImport.error_log``'s shape on
success — all writes use the
``{ "page_warnings": {...}, "page_failures": {...} }`` schema pinned
in #80's docstrings.

Notes-append anti-pattern explicitly NOT used (see #67/#69's race
fix). Status enum + error_log are the audit trail.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import ChartImport, ChartImportStatus
from .omr import (
    OmrLeadsheetError,
    OmrLeadsheetNotInstalled,
    OmrOutcome,
    OmrPipelineFailure,
    run_one_pdf,
)

_log = logging.getLogger(__name__)

# Page index for the v1 one-PDF-equals-one-song case. The splitter
# (#84) will replace this with a real per-page loop.
_V1_SINGLE_PAGE_KEY = "1"


@shared_task(bind=True, name="charts.process_pdf_chart")
def process_pdf_chart(self, chart_import_id: int) -> dict:
    """Run omr-leadsheet over one ChartImport's PDF. Idempotent on retry.

    Status transitions:
        PENDING/QUEUED/COMPLETE/FAILED/CANCELED → RUNNING (on entry)
        RUNNING → COMPLETE | PARTIAL | FAILED (terminal)

    Returns a dict with the final status + counts for the Celery
    result store; the canonical state is on the ChartImport row.

    Idempotency: a ChartImport in RUNNING when the worker picks it up
    (e.g. a redelivered message after a worker crash) does NOT loop —
    the orchestrator re-runs cleanly because omr-leadsheet's own
    caching skips already-done stages. If we ever see a redelivery
    storm we can add a worker-fence here; for v1 the cost of one
    redundant run is acceptable.
    """
    try:
        chart_import = ChartImport.objects.get(pk=chart_import_id)
    except ChartImport.DoesNotExist:
        _log.warning("process_pdf_chart: ChartImport %s not found", chart_import_id)
        return {"status": "not-found", "chart_import_id": chart_import_id}

    # Mark RUNNING immediately so the view layer's "what's in flight?"
    # query is accurate during the multi-minute omr-leadsheet run.
    chart_import.status = ChartImportStatus.RUNNING
    chart_import.save(update_fields=["status"])

    pdf_path = _resolve_pdf_path(chart_import.file_ref)
    if not pdf_path.is_file():
        return _fail(
            chart_import,
            page_idx=_V1_SINGLE_PAGE_KEY,
            message=f"PDF file missing on disk: {pdf_path}",
        )

    workspace_dir = _workspace_dir(chart_import_id)
    try:
        outcome = run_one_pdf(pdf_path, workspace_dir)
    except OmrLeadsheetNotInstalled as exc:
        # Infra-shaped failure — operator needs to pip install
        # omr-leadsheet, not debug the pipeline. Surface distinctly
        # so the admin error_log entry is actionable.
        return _fail(
            chart_import,
            page_idx=_V1_SINGLE_PAGE_KEY,
            message=f"omr-leadsheet not installed in worker: {exc}",
        )
    except OmrPipelineFailure as exc:
        return _fail(
            chart_import,
            page_idx=_V1_SINGLE_PAGE_KEY,
            message=f"omr-leadsheet pipeline failed: {exc}",
        )
    except OmrLeadsheetError as exc:
        # Catch-all for any future OmrLeadsheetError subclass we
        # haven't special-cased. Lands as FAILED with the message.
        return _fail(
            chart_import,
            page_idx=_V1_SINGLE_PAGE_KEY,
            message=f"omr-leadsheet error: {exc}",
        )

    return _ingest_outcome(chart_import, outcome)


# ---------------------------------------------------------------------------
# Dispatch helper (view layer + admin "re-process" use this)
# ---------------------------------------------------------------------------


def dispatch_pdf_chart(chart_import: ChartImport) -> str | None:
    """Mark a ChartImport QUEUED and enqueue ``process_pdf_chart``.

    Race-fix discipline from #67/#69:
    - Set QUEUED + save BEFORE ``.delay()`` so the worker can't pick
      up the row before its status reflects intent.
    - On broker failure, revert status to PENDING so the caller can
      retry without an orphan QUEUED row.

    Returns the Celery task ID on success, ``None`` on broker failure.
    """
    prior_status = chart_import.status
    chart_import.status = ChartImportStatus.QUEUED
    chart_import.save(update_fields=["status"])

    try:
        result = process_pdf_chart.delay(chart_import.pk)
    except Exception as exc:  # noqa: BLE001 — broker can raise many shapes
        _log.warning(
            "dispatch_pdf_chart: broker enqueue failed for ChartImport %s: %r",
            chart_import.pk,
            exc,
        )
        chart_import.status = prior_status
        chart_import.save(update_fields=["status"])
        return None

    chart_import.task_id = result.id
    chart_import.save(update_fields=["task_id"])
    return result.id


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve_pdf_path(file_ref: str) -> Path:
    """Map a ``ChartImport.file_ref`` opaque string to a disk path.

    The upload view (#82) writes uploaded PDFs at
    ``MEDIA_ROOT/pdf_upload/<sha>.pdf`` and stores the relative path
    ``"pdf_upload/<sha>.pdf"`` (or just ``"<sha>.pdf"``) in ``file_ref``.
    Path-traversal guard: refuse anything that resolves outside
    ``MEDIA_ROOT`` — same rule the audio uploader from #67 follows.
    """
    media_root = Path(settings.MEDIA_ROOT)
    candidate = (media_root / file_ref).resolve()
    if not candidate.is_relative_to(media_root.resolve()):
        raise ValueError(
            f"file_ref escapes MEDIA_ROOT: {file_ref!r}"
        )
    return candidate


def _workspace_dir(chart_import_id: int) -> Path:
    """Per-ChartImport workspace directory under MEDIA_ROOT.

    omr-leadsheet writes intermediate files (MusicXML/, Lyrics/,
    LeadSheets/<song>/) directly under its ``Config.book_dir``; we
    give each ChartImport its own subdir so concurrent runs don't
    collide on stem names.
    """
    base = Path(getattr(settings, "ELLINGTON_OMR_WORKSPACE_ROOT", None) or
                tempfile.gettempdir()) / "ellington-omr"
    workspace = base / f"chart-import-{chart_import_id}"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _ingest_outcome(
    chart_import: ChartImport,
    outcome: OmrOutcome,
) -> dict:
    """Pipe the produced .mscz into apps.charts via Phase 4-MS ingest.

    On Songbook absence (caller didn't set source_songbook), the
    Songs land in a default ``omr-imports`` Songbook auto-created
    here — same convention the design note on #70 documented.
    """
    from ingest.musescore.importer import import_parsed_songs
    from ingest.musescore.parser import parse_path

    songbook_slug = (
        chart_import.source_songbook.slug
        if chart_import.source_songbook
        else "omr-imports"
    )

    try:
        parsed = parse_path(outcome.mscz_path)
        summary = import_parsed_songs(
            parsed=parsed,
            songbook_slug=songbook_slug,
            songbook_title=(
                chart_import.source_songbook.title
                if chart_import.source_songbook
                else "OMR imports"
            ),
        )
    except Exception as exc:  # noqa: BLE001 — wrap as FAILED for the operator
        return _fail(
            chart_import,
            page_idx=_V1_SINGLE_PAGE_KEY,
            message=f"musescore ingest failed: {exc}",
        )

    # Backfill the ChartImport ↔ Song reverse link. The ingest layer
    # doesn't know about ChartImport (Phase 4-MS predates it); we
    # tag every Song the import touched here.
    from .models import Song

    Song.objects.filter(songbook__slug=songbook_slug).update(
        import_run=chart_import,
    )

    chart_import.page_count = 1
    chart_import.pages_succeeded = 1
    chart_import.pages_failed = 0
    if summary.warnings:
        chart_import.error_log = {
            "page_warnings": {_V1_SINGLE_PAGE_KEY: list(summary.warnings)},
            "page_failures": {},
        }
    chart_import.status = ChartImportStatus.COMPLETE
    chart_import.completed_at = timezone.now()
    chart_import.save()
    return {
        "status": ChartImportStatus.COMPLETE,
        "songs_created": summary.songs_created,
        "songs_updated": summary.songs_updated,
        "chart_import_id": chart_import.pk,
    }


def _fail(
    chart_import: ChartImport,
    *,
    page_idx: str,
    message: str,
) -> dict:
    """Land terminal FAILED on the ChartImport.

    Records the message in ``error_log['page_failures'][page_idx]``,
    sets page bookkeeping, never touches user-editable fields.
    """
    existing = chart_import.error_log or {}
    page_failures = dict(existing.get("page_failures", {}))
    page_failures[page_idx] = message
    chart_import.error_log = {
        "page_warnings": existing.get("page_warnings", {}),
        "page_failures": page_failures,
    }
    chart_import.page_count = chart_import.page_count or 1
    chart_import.pages_failed = (chart_import.pages_failed or 0) + 1
    chart_import.status = ChartImportStatus.FAILED
    chart_import.completed_at = timezone.now()
    chart_import.save()
    return {
        "status": ChartImportStatus.FAILED,
        "chart_import_id": chart_import.pk,
        "message": message,
    }


__all__ = ["dispatch_pdf_chart", "process_pdf_chart"]
