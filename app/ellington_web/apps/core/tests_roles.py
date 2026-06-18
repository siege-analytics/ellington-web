"""Tests for apps.core.roles — the role-helper seam.

Truth table for is_pedagogue / is_admin across:
- anonymous user
- authenticated user without profile
- authenticated user with profile, flag False
- authenticated user with profile, flag True
- staff user (is_admin True regardless of profile)
- superuser (is_admin True; is_pedagogue follows profile)

Plus minimal coverage for IsPedagogue DRF perm and pedagogue_required
decorator.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from apps.core.models import UserProfile
from apps.core.roles import (
    IsPedagogue,
    is_admin,
    is_pedagogue,
    pedagogue_required,
)


User = get_user_model()


class IsPedagogueTruthTableTests(TestCase):
    def test_anonymous_user_is_not_pedagogue(self):
        self.assertFalse(is_pedagogue(AnonymousUser()))

    def test_none_is_not_pedagogue(self):
        self.assertFalse(is_pedagogue(None))

    def test_authenticated_user_without_profile_is_not_pedagogue(self):
        u = User.objects.create(username="noprofile")
        self.assertFalse(is_pedagogue(u))

    def test_profile_flag_false_means_not_pedagogue(self):
        u = User.objects.create(username="general")
        UserProfile.objects.create(user=u, is_pedagogue=False)
        self.assertTrue(is_pedagogue(u) is False)

    def test_profile_flag_true_means_pedagogue(self):
        u = User.objects.create(username="trevor")
        UserProfile.objects.create(user=u, is_pedagogue=True)
        self.assertTrue(is_pedagogue(u))

    def test_staff_flag_alone_does_not_make_pedagogue(self):
        u = User.objects.create(username="admin1", is_staff=True)
        UserProfile.objects.create(user=u, is_pedagogue=False)
        self.assertFalse(is_pedagogue(u))


class IsAdminTruthTableTests(TestCase):
    def test_anonymous_user_is_not_admin(self):
        self.assertFalse(is_admin(AnonymousUser()))

    def test_regular_user_is_not_admin(self):
        u = User.objects.create(username="general")
        self.assertFalse(is_admin(u))

    def test_staff_user_is_admin(self):
        u = User.objects.create(username="staff1", is_staff=True)
        self.assertTrue(is_admin(u))

    def test_superuser_is_admin(self):
        u = User.objects.create(
            username="super1", is_staff=True, is_superuser=True,
        )
        self.assertTrue(is_admin(u))


class IsPedagoguePermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.perm = IsPedagogue()

    def test_anonymous_denied(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        self.assertFalse(self.perm.has_permission(request, view=None))

    def test_pedagogue_allowed(self):
        u = User.objects.create(username="trevor")
        UserProfile.objects.create(user=u, is_pedagogue=True)
        request = self.factory.get("/")
        request.user = u
        self.assertTrue(self.perm.has_permission(request, view=None))


class PedagogueRequiredDecoratorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        @pedagogue_required
        def my_view(request):
            return HttpResponse("ok")

        self.view = my_view

    def test_anonymous_403(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 403)

    def test_pedagogue_200(self):
        u = User.objects.create(username="trevor")
        UserProfile.objects.create(user=u, is_pedagogue=True)
        request = self.factory.get("/")
        request.user = u
        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
