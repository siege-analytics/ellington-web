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
        PENDING / COMPLETE / FAILED → QUEUED (set by the dispatcher
            before calling .delay())
        QUEUED → RUNNING (this task, on entry)
        RUNNING → COMPLETE (on successful return)
        RUNNING → FAILED (on exception)

    The dispatcher (view layer) is responsible for stamping
    ``analysis_task_id`` + flipping status to QUEUED before
    ``.delay()``. This task assumes those are already set.

    Returns a dict suitable for Celery result-backend storage (just
    counters; not the actual detection rows — those live in the DB).
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
            "analyze_recording %s failed", recording_id
        )
        Recording.objects.filter(pk=recording.pk).update(
            analysis_status=AnalysisStatus.FAILED,
            notes=(recording.notes or "")
            + f"\n[analysis_error] {type(exc).__name__}: {exc!r}",
        )
        raise

    Recording.objects.filter(pk=recording.pk).update(
        analysis_status=AnalysisStatus.COMPLETE,
        analysis_completed_at=timezone.now(),
        notes=(recording.notes or "") + f"\n[analysis] {outcome.notes}",
    )
    return {
        "status": "complete",
        "recording_id": recording_id,
        "detections_written": outcome.detections_written,
        "duration_seconds_estimated": outcome.duration_seconds_estimated,
    }


def dispatch_analysis(recording: Recording) -> str | None:
    """Helper called by the view layer to fire the task.

    Sets ``analysis_status=QUEUED`` and ``analysis_task_id``, then
    calls ``.delay()``. Returns the Celery task ID for logging.
    Returns None and logs a warning if the dispatch fails (e.g. broker
    unreachable) — the recording stays in its previous status so the
    user can re-try.

    The dispatcher is sync (cheap DB update + AMQP enqueue); the actual
    analysis runs async on the worker.
    """
    try:
        async_result = analyze_recording.delay(recording.pk)
    except Exception as exc:  # noqa: BLE001 — broker errors must not crash views
        _log.exception(
            "dispatch_analysis: broker enqueue failed for recording %s",
            recording.pk,
        )
        return None

    Recording.objects.filter(pk=recording.pk).update(
        analysis_status=AnalysisStatus.QUEUED,
        analysis_task_id=async_result.id,
    )
    _log.info(
        "dispatch_analysis: recording %s queued as %s",
        recording.pk,
        async_result.id,
    )
    return async_result.id


__all__ = ["analyze_recording", "dispatch_analysis"]
