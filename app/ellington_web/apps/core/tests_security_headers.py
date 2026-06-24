"""Tests for SecurityHeadersMiddleware — #227."""

from __future__ import annotations

from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from apps.core.middleware import (
    DEFAULT_CSP,
    DEFAULT_PERMISSIONS_POLICY,
    DEFAULT_REFERRER_POLICY,
    SecurityHeadersMiddleware,
)


def _get_response(_request):
    return HttpResponse("ok")


class SecurityHeadersMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _process(self):
        mw = SecurityHeadersMiddleware(_get_response)
        return mw(self.factory.get("/"))

    def test_csp_set_by_default(self):
        response = self._process()
        self.assertEqual(
            response["Content-Security-Policy"], DEFAULT_CSP,
        )

    def test_permissions_policy_set_by_default(self):
        response = self._process()
        self.assertEqual(
            response["Permissions-Policy"], DEFAULT_PERMISSIONS_POLICY,
        )

    def test_referrer_policy_set_by_default(self):
        response = self._process()
        self.assertEqual(
            response["Referrer-Policy"], DEFAULT_REFERRER_POLICY,
        )

    def test_nosniff_set_as_defensive_belt(self):
        response = self._process()
        self.assertEqual(
            response["X-Content-Type-Options"], "nosniff",
        )

    @override_settings(SECURITY_HEADERS_CSP="default-src 'self'; script-src 'self'")
    def test_csp_override(self):
        response = self._process()
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertNotIn("unpkg.com", response["Content-Security-Policy"])

    @override_settings(SECURITY_HEADERS_CSP=None)
    def test_csp_disabled_when_none(self):
        response = self._process()
        self.assertNotIn("Content-Security-Policy", response)

    @override_settings(SECURITY_HEADERS_CSP="")
    def test_csp_disabled_when_empty(self):
        response = self._process()
        self.assertNotIn("Content-Security-Policy", response)

    def test_does_not_overwrite_existing_csp(self):
        """A view that sets its own CSP (e.g. an embed endpoint) wins."""
        def view_with_csp(_request):
            resp = HttpResponse("ok")
            resp["Content-Security-Policy"] = "frame-ancestors *"
            return resp

        mw = SecurityHeadersMiddleware(view_with_csp)
        response = mw(self.factory.get("/"))
        self.assertEqual(
            response["Content-Security-Policy"], "frame-ancestors *",
        )
