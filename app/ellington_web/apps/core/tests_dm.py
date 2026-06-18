"""Tests for DirectMessage (epic #96 sub-ticket g / #124)."""

from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.core.models import DirectMessage


User = get_user_model()


class DirectMessageModelTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )

    def test_self_send_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            DirectMessage.objects.create(
                sender=self.alice, recipient=self.alice, body="hi me",
            )


class DMInboxTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        self.eve = User.objects.create_user(
            username="eve", password=secrets.token_urlsafe(16),
        )

    def test_anonymous_redirects(self):
        response = self.client.get(reverse("dm_inbox"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_inbox_empty_when_no_messages(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("dm_inbox"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No conversations yet")

    def test_inbox_shows_partner_with_unread_count(self):
        DirectMessage.objects.create(
            sender=self.bob, recipient=self.alice, body="hello",
        )
        self.client.force_login(self.alice)
        response = self.client.get(reverse("dm_inbox"))
        self.assertContains(response, "bob")
        self.assertContains(response, "1 unread")

    def test_inbox_only_shows_own_conversations(self):
        DirectMessage.objects.create(
            sender=self.bob, recipient=self.eve, body="ghost",
        )
        self.client.force_login(self.alice)
        response = self.client.get(reverse("dm_inbox"))
        self.assertNotContains(response, "bob")
        self.assertNotContains(response, "eve")


class DMThreadTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )

    def test_get_marks_incoming_as_read(self):
        DirectMessage.objects.create(
            sender=self.bob, recipient=self.alice, body="unread",
        )
        self.client.force_login(self.alice)
        response = self.client.get(
            reverse("dm_thread", args=["bob"])
        )
        self.assertEqual(response.status_code, 200)
        msg = DirectMessage.objects.get()
        self.assertIsNotNone(msg.read_at)

    def test_post_creates_message(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("dm_thread", args=["bob"]),
            {"body": "hi there"},
        )
        self.assertEqual(response.status_code, 302)
        msg = DirectMessage.objects.get()
        self.assertEqual(msg.sender, self.alice)
        self.assertEqual(msg.recipient, self.bob)
        self.assertEqual(msg.body, "hi there")

    def test_empty_body_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("dm_thread", args=["bob"]),
            {"body": "   "},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DirectMessage.objects.count(), 0)

    def test_self_thread_redirects_to_inbox(self):
        self.client.force_login(self.alice)
        response = self.client.get(
            reverse("dm_thread", args=["alice"])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/messages/", response.url)

    def test_thread_shows_both_directions(self):
        DirectMessage.objects.create(
            sender=self.alice, recipient=self.bob, body="hi bob",
        )
        DirectMessage.objects.create(
            sender=self.bob, recipient=self.alice, body="hi alice",
        )
        self.client.force_login(self.alice)
        response = self.client.get(
            reverse("dm_thread", args=["bob"])
        )
        self.assertContains(response, "hi bob")
        self.assertContains(response, "hi alice")
