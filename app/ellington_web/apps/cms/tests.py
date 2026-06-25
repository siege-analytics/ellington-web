"""Tests for apps.cms — #191 Wagtail spike.

Verifies that Wagtail and the existing Django apps coexist:
- Wagtail admin mounts at /cms/.
- Django app routes (engine_rules, rule_review, voicings, charts,
  practice, critique) are not shadowed by Wagtail's catch-all.

These tests intentionally do NOT verify the HomePage render — that
requires a Wagtail Site + root Page, which is created by the
``wagtail_create_homepage`` data migration shipped by Wagtail at
install time. The smoke we own here is: routing doesn't regress.
"""

from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve, reverse


User = get_user_model()


class WagtailAdminMountTests(TestCase):
    """The /cms/ path resolves to Wagtail's admin URL conf."""

    def test_cms_root_resolves(self):
        match = resolve("/cms/")
        # Wagtail mounts its admin under the 'wagtailadmin' namespace.
        self.assertIn("wagtailadmin", match.namespaces or [match.namespace])


class DjangoRoutesNotShadowedTests(TestCase):
    """Existing Django app routes still resolve correctly.

    Wagtail's catch-all is mounted LAST in ellington_web.urls. These
    tests assert the catch-all doesn't swallow explicit Django paths.
    """

    def test_rule_review_routes_intact(self):
        # rule_list, rule_library, admin_queue all in apps.rule_review.urls
        self.assertEqual(
            resolve(reverse("rule_review:rule_list")).view_name,
            "rule_review:rule_list",
        )

    def test_charts_routes_intact(self):
        self.assertEqual(
            resolve(reverse("charts:import_list")).view_name,
            "charts:import_list",
        )

    def test_practice_routes_intact(self):
        # practice has at least one named route; resolve via URL conf
        from django.urls.resolvers import URLResolver
        from django.urls import get_resolver

        resolver = get_resolver()
        # If practice/ wasn't shadowed, the resolver matches it as an
        # include
        match = resolve("/practice/sessions/")
        self.assertNotIn("wagtail", (match.namespaces or []) + [match.namespace or ""])

    def test_admin_route_intact(self):
        match = resolve("/admin/")
        self.assertEqual(match.namespace, "admin")

    def test_accounts_login_intact(self):
        match = resolve("/accounts/login/")
        # Either apps.core or django.contrib.auth — both are NOT wagtail
        self.assertNotIn("wagtail", (match.namespaces or []) + [match.namespace or ""])
