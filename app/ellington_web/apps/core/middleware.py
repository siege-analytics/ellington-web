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


# ---------------------------------------------------------------------------
# Security headers middleware (#227)
# ---------------------------------------------------------------------------


from django.conf import settings  # noqa: E402


# Defaults that work for the existing surface:
# - WhiteNoise serves hashed static, all from self
# - Wagtail (#190) admin loads its own JS/CSS, all from self
# - HTMX is vendored at static/js/htmx.min.js (#229) so no external
#   script origins are needed
# - Authentik may redirect us; same-origin form-action is fine
# - No camera/mic/geo usage today; disable broadly
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'self'; "
    "form-action 'self'; "
    "base-uri 'self'"
)

DEFAULT_PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
)

DEFAULT_REFERRER_POLICY = "strict-origin-when-cross-origin"


class SecurityHeadersMiddleware:
    """Set baseline security headers per #227.

    Each header is settings-driven so an environment can override:
    - SECURITY_HEADERS_CSP
    - SECURITY_HEADERS_PERMISSIONS_POLICY
    - SECURITY_HEADERS_REFERRER_POLICY

    Setting a value to None or empty string disables that header.

    Headers are added on the response; existing values (Django's
    own X-Frame-Options, etc.) are preserved.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        csp = getattr(settings, "SECURITY_HEADERS_CSP", DEFAULT_CSP)
        if csp and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = csp
        pp = getattr(
            settings, "SECURITY_HEADERS_PERMISSIONS_POLICY",
            DEFAULT_PERMISSIONS_POLICY,
        )
        if pp and "Permissions-Policy" not in response:
            response["Permissions-Policy"] = pp
        rp = getattr(
            settings, "SECURITY_HEADERS_REFERRER_POLICY",
            DEFAULT_REFERRER_POLICY,
        )
        if rp and "Referrer-Policy" not in response:
            response["Referrer-Policy"] = rp
        # X-Content-Type-Options is set by Django's SecurityMiddleware
        # when SECURE_CONTENT_TYPE_NOSNIFF=True; setting it here would
        # double up. We add it only as a defensive belt if the upstream
        # middleware skipped it.
        if "X-Content-Type-Options" not in response:
            response["X-Content-Type-Options"] = "nosniff"
        return response
