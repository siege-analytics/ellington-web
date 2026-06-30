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
# #196 — Pedagogue Wagtail group sync
# ---------------------------------------------------------------------------


from django.contrib.auth.models import Group  # noqa: E402

from apps.core.models import UserProfile  # noqa: E402


PEDAGOGUE_GROUP_NAME = "Pedagogue"


class PedagogueGroupSyncTests(TestCase):
    """The Pedagogue Wagtail Group exists (migration 0002) and
    UserProfile.is_pedagogue toggles drive Group membership."""

    def test_group_exists_after_migration(self):
        self.assertTrue(
            Group.objects.filter(name=PEDAGOGUE_GROUP_NAME).exists(),
            "Migration 0002_pedagogue_group should have created the "
            "Pedagogue Wagtail Group.",
        )

    def test_promotion_adds_user_to_group(self):
        user = User.objects.create_user(
            username="new-pedagogue", password=secrets.token_urlsafe(16),
        )
        profile = UserProfile.objects.create(user=user, is_pedagogue=False)

        # Re-load to populate _initial_role_values via post_init
        profile = UserProfile.objects.get(pk=profile.pk)
        profile.is_pedagogue = True
        profile.save()

        group = Group.objects.get(name=PEDAGOGUE_GROUP_NAME)
        self.assertIn(group, user.groups.all())

    def test_demotion_removes_user_from_group(self):
        user = User.objects.create_user(
            username="ex-pedagogue", password=secrets.token_urlsafe(16),
        )
        UserProfile.objects.create(user=user, is_pedagogue=True)
        group = Group.objects.get(name=PEDAGOGUE_GROUP_NAME)
        user.groups.add(group)

        profile = UserProfile.objects.get(user=user)
        profile.is_pedagogue = False
        profile.save()

        self.assertNotIn(group, user.groups.all())

    def test_signal_is_noop_when_no_change(self):
        """Saving the profile without changing is_pedagogue doesn't
        thrash group membership."""
        user = User.objects.create_user(
            username="stable-pedagogue", password=secrets.token_urlsafe(16),
        )
        UserProfile.objects.create(user=user, is_pedagogue=True)
        group = Group.objects.get(name=PEDAGOGUE_GROUP_NAME)
        user.groups.add(group)
        before = set(user.groups.values_list("name", flat=True))

        profile = UserProfile.objects.get(user=user)
        profile.save()  # no field change

        after = set(user.groups.values_list("name", flat=True))
        self.assertEqual(before, after)


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
