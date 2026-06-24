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
# #205 — pedagogue subtree restriction
# ---------------------------------------------------------------------------


class PedagogueSubtreeRestrictionTests(TestCase):
    """Post-migration the Pedagogue group has subtree-only perms.

    The wagtail_create_homepage initial migration creates a root and
    a HomePage at depth=2 (slug='home' by default). Our 0002 grants
    root-level GroupPagePermission; 0003 removes that and re-grants
    per-slug. After both migrations have run, the group should NOT
    have any GroupPagePermission on the root page.
    """

    def test_root_level_permission_removed(self):
        try:
            from wagtail.models import GroupPagePermission, Page
        except ImportError:
            self.skipTest("wagtail not installed")

        group = Group.objects.filter(name=PEDAGOGUE_GROUP_NAME).first()
        if group is None:
            self.skipTest("Pedagogue group not seeded (migration 0002 skipped)")

        root = Page.objects.filter(pk=1).first()
        if root is None:
            self.skipTest("Wagtail root page not present")

        self.assertEqual(
            GroupPagePermission.objects.filter(group=group, page=root).count(),
            0,
            "0003 should have removed root-level GroupPagePermission.",
        )

    def test_access_admin_permission_preserved(self):
        """Pedagogue can still log into /cms/ even with no subtrees."""
        from django.contrib.auth.models import Permission

        group = Group.objects.filter(name=PEDAGOGUE_GROUP_NAME).first()
        if group is None:
            self.skipTest("Pedagogue group not seeded")

        access_admin = Permission.objects.filter(
            content_type__app_label="wagtailadmin",
            codename="access_admin",
        ).first()
        if access_admin is None:
            self.skipTest("access_admin permission not installed")

        self.assertIn(access_admin, group.permissions.all())
