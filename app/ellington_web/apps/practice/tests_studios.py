"""Tests for Studios (epic #96 sub-ticket f / #120)."""

from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.practice.models import Studio, StudioMember, StudioRole, StudioVisibility


User = get_user_model()


class StudioModelTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )

    def test_unique_member_per_studio(self):
        studio = Studio.objects.create(
            slug="s1", name="S1", owner=self.alice,
        )
        StudioMember.objects.create(
            studio=studio, user=self.alice, role=StudioRole.MODERATOR,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudioMember.objects.create(
                studio=studio, user=self.alice, role=StudioRole.MEMBER,
            )


class StudioCreateViewTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )

    def test_login_required(self):
        response = self.client.get(reverse("practice:studio_create"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_create_studio_with_owner_as_moderator(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("practice:studio_create"),
            {"name": "My Studio", "visibility": "public"},
        )
        self.assertEqual(response.status_code, 302)
        studio = Studio.objects.get()
        self.assertEqual(studio.name, "My Studio")
        self.assertEqual(studio.owner, self.alice)
        self.assertEqual(studio.visibility, "public")
        # Owner is auto-added as moderator
        member = StudioMember.objects.get(studio=studio, user=self.alice)
        self.assertEqual(member.role, StudioRole.MODERATOR)

    def test_slug_uniqueness_handled(self):
        self.client.force_login(self.alice)
        Studio.objects.create(slug="my-studio", name="X", owner=self.alice)
        response = self.client.post(
            reverse("practice:studio_create"),
            {"name": "My Studio"},
        )
        self.assertEqual(response.status_code, 302)
        # Two studios with similar slug
        self.assertEqual(Studio.objects.filter(slug__startswith="my-studio").count(), 2)

    def test_empty_name_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("practice:studio_create"),
            {"name": ""},
        )
        # Form re-renders, no Studio created
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Studio.objects.count(), 0)


class StudioVisibilityTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )

    def test_public_studio_visible_to_non_member(self):
        studio = Studio.objects.create(
            slug="public", name="Public Jam", owner=self.alice,
            visibility=StudioVisibility.PUBLIC,
        )
        self.client.force_login(self.bob)
        response = self.client.get(
            reverse("practice:studio_detail", args=[studio.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Public Jam")

    def test_private_studio_404s_for_non_member(self):
        studio = Studio.objects.create(
            slug="priv", name="Private Group", owner=self.alice,
            visibility=StudioVisibility.PRIVATE,
        )
        self.client.force_login(self.bob)
        response = self.client.get(
            reverse("practice:studio_detail", args=[studio.slug])
        )
        self.assertEqual(response.status_code, 404)

    def test_private_studio_visible_to_member(self):
        studio = Studio.objects.create(
            slug="priv", name="Private Group", owner=self.alice,
            visibility=StudioVisibility.PRIVATE,
        )
        StudioMember.objects.create(
            studio=studio, user=self.bob, role=StudioRole.MEMBER,
        )
        self.client.force_login(self.bob)
        response = self.client.get(
            reverse("practice:studio_detail", args=[studio.slug])
        )
        self.assertEqual(response.status_code, 200)


class StudioJoinLeaveTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        self.public = Studio.objects.create(
            slug="p", name="Public", owner=self.alice,
            visibility=StudioVisibility.PUBLIC,
        )
        self.private = Studio.objects.create(
            slug="pr", name="Private", owner=self.alice,
            visibility=StudioVisibility.PRIVATE,
        )

    def test_join_public_studio(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("practice:studio_join", args=[self.public.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            StudioMember.objects.filter(
                studio=self.public, user=self.bob,
            ).exists()
        )

    def test_join_private_studio_forbidden(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("practice:studio_join", args=[self.private.slug])
        )
        self.assertEqual(response.status_code, 403)

    def test_banned_user_cannot_rejoin(self):
        StudioMember.objects.create(
            studio=self.public, user=self.bob, role=StudioRole.BANNED,
        )
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("practice:studio_join", args=[self.public.slug])
        )
        self.assertEqual(response.status_code, 403)

    def test_leave_studio(self):
        StudioMember.objects.create(
            studio=self.public, user=self.bob, role=StudioRole.MEMBER,
        )
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("practice:studio_leave", args=[self.public.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            StudioMember.objects.filter(
                studio=self.public, user=self.bob,
            ).exists()
        )

    def test_owner_cannot_leave(self):
        StudioMember.objects.create(
            studio=self.public, user=self.alice, role=StudioRole.MODERATOR,
        )
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("practice:studio_leave", args=[self.public.slug])
        )
        self.assertEqual(response.status_code, 302)
        # Owner's membership still there
        self.assertTrue(
            StudioMember.objects.filter(
                studio=self.public, user=self.alice,
            ).exists()
        )
