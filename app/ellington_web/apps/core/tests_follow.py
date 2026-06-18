"""Tests for Follow + profile + feed (epic #96 sub-ticket h / #122)."""

from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Follow


User = get_user_model()


class FollowModelTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )

    def test_basic_follow(self):
        Follow.objects.create(follower=self.alice, followed=self.bob)
        self.assertEqual(
            Follow.objects.filter(follower=self.alice, followed=self.bob).count(),
            1,
        )

    def test_unique_constraint(self):
        Follow.objects.create(follower=self.alice, followed=self.bob)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Follow.objects.create(follower=self.alice, followed=self.bob)

    def test_self_follow_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Follow.objects.create(follower=self.alice, followed=self.alice)


class UserProfileViewTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )

    def test_profile_visible_anonymously(self):
        response = self.client.get(
            reverse("user_profile", args=["alice"])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "alice")

    def test_profile_shows_follow_button_for_authenticated_non_self(self):
        self.client.force_login(self.bob)
        response = self.client.get(
            reverse("user_profile", args=["alice"])
        )
        self.assertContains(response, "Follow</button>")

    def test_profile_hides_button_for_self(self):
        self.client.force_login(self.alice)
        response = self.client.get(
            reverse("user_profile", args=["alice"])
        )
        self.assertNotContains(response, "Follow</button>")
        self.assertNotContains(response, "Unfollow</button>")

    def test_profile_shows_unfollow_when_following(self):
        Follow.objects.create(follower=self.bob, followed=self.alice)
        self.client.force_login(self.bob)
        response = self.client.get(
            reverse("user_profile", args=["alice"])
        )
        self.assertContains(response, "Unfollow</button>")


class FollowActionTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )

    def test_follow_post_creates_row(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("follow_user", args=["alice"])
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Follow.objects.filter(follower=self.bob, followed=self.alice).exists()
        )

    def test_follow_self_rejected_at_view(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("follow_user", args=["alice"])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Follow.objects.filter(follower=self.alice, followed=self.alice).exists()
        )

    def test_follow_idempotent(self):
        self.client.force_login(self.bob)
        for _ in range(2):
            self.client.post(reverse("follow_user", args=["alice"]))
        self.assertEqual(
            Follow.objects.filter(follower=self.bob, followed=self.alice).count(),
            1,
        )

    def test_unfollow_deletes_row(self):
        Follow.objects.create(follower=self.bob, followed=self.alice)
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("unfollow_user", args=["alice"])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Follow.objects.filter(follower=self.bob, followed=self.alice).exists()
        )


class FeedTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_feed_empty_when_no_follows(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nothing yet")
