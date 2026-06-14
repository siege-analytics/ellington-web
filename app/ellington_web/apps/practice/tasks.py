"""Celery tasks for the practice-flow audio pipeline.

Celery autodiscovery picks this up via ``app.autodiscover_tasks()`` in
``ellington_web/celery.py``. The single task here, ``analyze_recording``,
takes a Recording PK, walks the lifecycle states on
``Recording.analysis_status``, and delegates the actual analysis to
:func:`apps.practice.analysis.analyze_recording_placeholder` (Phase 3a)
or to the real detector in Phase 3b.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from .analysis import analyze_recording_placeholder
from .models import AnalysisStatus, Recording

_log = logging.getLogger(__name__)


@shared_task(bind=True, name="practice.analyze_recording")
def analyze_recording(self, recording_id: int) -> dict:
    """Run analysis on one Recording. Idempotent.

    Status transitions:
        PENDING / QUEUED / COMPLETE / FAILED → RUNNING (this task, on entry)
        RUNNING → COMPLETE (on successful return)
        RUNNING → FAILED (on exception)

    The dispatcher (view layer) stamps ``analysis_task_id`` and
    (optionally) sets ``analysis_status=QUEUED``; this task is
    indifferent to the prior status and flips straight to RUNNING.
    Audit history lives in ``analysis_completed_at`` + structured logs;
    we deliberately do NOT mutate ``Recording.notes`` from inside the
    worker (see ``Notes-append removed`` below).

    Returns a dict suitable for Celery result-backend storage (just
    counters; not the actual detection rows — those live in the DB).

    **Notes-append removed (post-review fix)**

    A prior version of this task did
    ``notes=(recording.notes or '') + ...`` inside the terminal
    ``UPDATE``. That pattern reads ``recording.notes`` into memory at
    task start, then writes the *stale* base plus an appended fragment
    — which silently overwrites concurrent edits (form-side note
    edits; second analyze call via Re-analyze; Celery redelivery with
    ``acks_late=True``). The new code logs analysis events via
    ``_log.info`` only — structured logs are the audit trail. The
    ``analysis_status`` enum + ``analysis_completed_at`` cover the UI
    surface.
    """
    try:
        recording = Recording.objects.select_related("session__song").get(
            pk=recording_id
        )
    except Recording.DoesNotExist:
        _log.warning("analyze_recording: recording %s not found", recording_id)
        return {"status": "not-found", "recording_id": recording_id}

    Recording.objects.filter(pk=recording.pk).update(
        analysis_status=AnalysisStatus.RUNNING
    )

    try:
        outcome = analyze_recording_placeholder(recording)
    except Exception as exc:  # noqa: BLE001 — task-level: report and persist
        _log.exception(
            "analyze_recording %s failed: %s: %r",
            recording_id,
            type(exc).__name__,
            exc,
        )
        Recording.objects.filter(pk=recording.pk).update(
            analysis_status=AnalysisStatus.FAILED,
        )
        raise

    _log.info(
        "analyze_recording %s complete: %s",
        recording_id,
        outcome.notes,
    )
    Recording.objects.filter(pk=recording.pk).update(
        analysis_status=AnalysisStatus.COMPLETE,
        analysis_completed_at=timezone.now(),
    )
    return {
        "status": "complete",
        "recording_id": recording_id,
        "detections_written": outcome.detections_written,
        "duration_seconds_estimated": outcome.duration_seconds_estimated,
    }


def dispatch_analysis(recording: Recording) -> str | None:
    """Helper called by the view layer to fire the task.

    Flips ``analysis_status=QUEUED`` BEFORE calling ``.delay()`` so a
    fast worker that picks up the task immediately doesn't observe a
    stale prior status when it flips to RUNNING. The ``analysis_task_id``
    is set in a second UPDATE after ``.delay()`` returns; that field is
    diagnostic only (ops debugging) and a small write-after-delay race
    on the ID is acceptable.

    Returns the Celery task ID for logging. Returns None and logs a
    warning if the dispatch fails (e.g. broker unreachable) — the
    recording stays in its previous status so the user can re-try.

    The dispatcher is sync (cheap DB update + AMQP enqueue); the actual
    analysis runs async on the worker.
    """
    # Set QUEUED first so the worker can't observe a stale prior
    # status. If .delay() fails we revert in the except block below.
    prior_status = recording.analysis_status
    Recording.objects.filter(pk=recording.pk).update(
        analysis_status=AnalysisStatus.QUEUED
    )

    try:
        async_result = analyze_recording.delay(recording.pk)
    except Exception:  # noqa: BLE001 — broker errors must not crash views
        _log.exception(
            "dispatch_analysis: broker enqueue failed for recording %s",
            recording.pk,
        )
        # Revert to prior status so the UI doesn't show a stuck QUEUED
        # row that no worker will ever pick up.
        Recording.objects.filter(pk=recording.pk).update(
            analysis_status=prior_status
        )
        return None

    # task_id is diagnostic only — small race on this UPDATE is fine
    Recording.objects.filter(pk=recording.pk).update(
        analysis_task_id=async_result.id,
    )
    _log.info(
        "dispatch_analysis: recording %s queued as %s",
        recording.pk,
        async_result.id,
    )
    return async_result.id


__all__ = ["analyze_recording", "dispatch_analysis"]
