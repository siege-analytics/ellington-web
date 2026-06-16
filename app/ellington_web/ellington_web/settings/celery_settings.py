"""Celery configuration — broker URL is set elsewhere; this module owns queues.

Celery autodiscovery picks up tasks from each app's ``tasks.py``. By
default everything lands on the ``celery`` queue. We override that for
specific tasks where queue isolation matters:

- ``practice.analyze_recording`` (#67, #69): stays on the default
  queue. Audio analysis is fast (seconds), high-volume.
- ``charts.process_pdf_chart`` (#81, depends on this module): routes
  to ``omr-leadsheet``. omr-leadsheet runs minutes per page (Audiveris
  JVM + VLM + music21), and we don't want a long-running PDF import to
  starve sub-4 audio analysis for the user who's actively practicing.

Worker deployment then runs (at least) two workers:

- ``celery -A ellington_web worker -Q celery`` — default queue
- ``celery -A ellington_web worker -Q omr-leadsheet -c 1`` — dedicated
  omr-leadsheet worker; concurrency 1 because Audiveris JVM + GPU VLM
  contend badly for memory on cyberpower.

The ``namespace='CELERY'`` in ``ellington_web/celery.py`` means every
key here must have a ``CELERY_`` prefix to be picked up.
"""

from __future__ import annotations

# Task → queue map. Keys are task names (Celery's ``@shared_task`` /
# ``@app.task`` ``name=`` kwarg), values are the queue to route to.
# Tasks not listed land on the default ``celery`` queue.
CELERY_TASK_ROUTES = {
    "charts.process_pdf_chart": {"queue": "omr-leadsheet"},
}

# Surface broker errors fast — beats a request hanging on a silent
# broker outage. The Recording dispatch helper from #69 already catches
# this for the audio path; the ChartImport dispatch helper in #81 will
# do the same.
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
