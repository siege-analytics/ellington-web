"""Thread-local middleware for capturing request.user in signal handlers.

Django signals (pre_save / post_save) don't see the HTTP request, so a
field-change audit signal can't know who triggered the change. This
middleware stashes ``request.user`` on a thread-local for the signal
handler in ``apps.core.signals`` to read.

Threading is safe for synchronous WSGI/ASGI requests; for long-running
Celery tasks or management commands the thread-local will be empty and
the audit row falls back to ``promoted_by_username = 'system'``.
"""

from __future__ import annotations

import threading
from typing import Optional


_thread_local = threading.local()


class CurrentUserMiddleware:
    """Stashes ``request.user`` on a thread-local for the duration of the
    request. Must be installed AFTER AuthenticationMiddleware so
    ``request.user`` is populated.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_local.current_user = getattr(request, "user", None)
        try:
            return self.get_response(request)
        finally:
            _thread_local.current_user = None


def get_current_user() -> Optional[object]:
    """Return the request user stashed by CurrentUserMiddleware, or None."""
    return getattr(_thread_local, "current_user", None)
