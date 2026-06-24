"""Tests for apps.cms — #191 Wagtail spike + #194 brand integration.

Verifies that Wagtail and the existing Django apps coexist:
- Wagtail admin mounts at /cms/.
- Django app routes are not shadowed by Wagtail's catch-all.
- All app pages render with the shared shell marker
  (id="ellington-nav" from templates/_site_nav.html).
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
        match = resolve("/practice/sessions/")
        self.assertNotIn("wagtail", (match.namespaces or []) + [match.namespace or ""])

    def test_admin_route_intact(self):
        match = resolve("/admin/")
        self.assertEqual(match.namespace, "admin")

    def test_accounts_login_intact(self):
        match = resolve("/accounts/login/")
        self.assertNotIn("wagtail", (match.namespaces or []) + [match.namespace or ""])


class SharedShellTests(TestCase):
    """#194 — every Django-served page should render the shared shell.

    The marker is ``id="ellington-nav"`` in templates/_site_nav.html.
    Apps that extend templates/base.html inherit the shell; if any
    template was left stranded on its old standalone base.html, the
    marker won't appear.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="shell-tester", password=secrets.token_urlsafe(16),
        )

    def test_rule_library_carries_shell(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("rule_review:rule_library"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="ellington-nav"')

    # Voicings shell test lands as a follow-up once apps.voicings
    # merges (PR #188). This branch doesn't have apps.voicings.


# ---------------------------------------------------------------------------
# #198 — MasterProfilePage
# ---------------------------------------------------------------------------


class MasterProfilePageTests(TestCase):
    """Joe Pass page is seeded by migration 0004 and renders with shell."""

    def test_joe_pass_page_renders(self):
        response = self.client.get("/masters/joe-pass/")
        # 200 if Wagtail's site middleware found the page; 404 if seed
        # didn't run (which would be a migration bug).
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertContains(response, "Joe Pass")

    def test_masters_index_renders(self):
        response = self.client.get("/masters/")
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertContains(response, "Joe Pass")

    def test_master_profile_carries_shell(self):
        response = self.client.get("/masters/joe-pass/")
        self.assertContains(response, 'id="ellington-nav"')


# ---------------------------------------------------------------------------
# #200 — engine_rule_reference StreamField block
# ---------------------------------------------------------------------------


from apps.cms.blocks import EngineRuleReferenceBlock  # noqa: E402
from apps.engine_rules.models import EngineRule, EngineRulesBundle  # noqa: E402
from apps.styles.models import Master as StylesMaster  # noqa: E402
from datetime import datetime, timezone as dt_timezone  # noqa: E402


def _make_engine_rule_bundle():
    return EngineRulesBundle.objects.create(
        bundle_version="0.2.0",
        schema_version="0.2",
        plugin_commit_sha="b" * 40,
        built_at=datetime(2026, 6, 24, tzinfo=dt_timezone.utc),
        total_rules=0,
        manifest={"bundle_version": "0.2.0"},
    )


class EngineRuleReferenceBlockTests(TestCase):
    """The block resolves rule_id → live EngineRule at render time."""

    def setUp(self):
        bundle = _make_engine_rule_bundle()
        self.master = StylesMaster.objects.create(
            slug="joe-pass-rb", name="Joe Pass (test)",
        )
        self.rule = EngineRule.objects.create(
            bundle=bundle,
            master=self.master,
            work_id="virtuoso",
            rule_id="joe-pass-r-001",
            name="prefer 137 shell on Cmaj7",
            preference=2,
            quality_binding=["maj7"],
            applicability_reasons=[],
            when_predicate={},
            then_action={"voicing.shape": "shell_137"},
            anchor="Joe's voicing on Stella, Verve 1973",
            is_active=True,
        )

    def test_block_resolves_active_rule(self):
        block = EngineRuleReferenceBlock()
        context = block.get_context(
            {"rule_id": "joe-pass-r-001", "show_anchor": True},
        )
        self.assertIsNotNone(context["token"])
        self.assertEqual(context["token"]["payload"]["rule_id"], "joe-pass-r-001")
        self.assertEqual(context["token"]["source"], "rule")

    def test_block_falls_back_for_missing_rule(self):
        block = EngineRuleReferenceBlock()
        context = block.get_context(
            {"rule_id": "nonexistent-rule", "show_anchor": True},
        )
        self.assertIsNone(context["token"])
        self.assertEqual(context["unavailable_rule_id"], "nonexistent-rule")

    def test_block_excludes_inactive_rule(self):
        self.rule.is_active = False
        self.rule.save(update_fields=["is_active"])
        block = EngineRuleReferenceBlock()
        context = block.get_context(
            {"rule_id": "joe-pass-r-001", "show_anchor": True},
        )
        self.assertIsNone(context["token"])
