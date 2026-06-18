"""Tests for Songbook sharing (epic #96 sub-ticket c / #137)."""

from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.charts.models import (
    Songbook,
    SongbookShare,
    SongbookVisibility,
)
from apps.charts.permissions import can_access_songbook, is_songbook_owner
from apps.practice.models import (
    Studio,
    StudioMember,
    StudioRole,
    StudioVisibility,
)


User = get_user_model()


class CanAccessSongbookTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )

    def test_public_songbook_accessible_to_any_auth_user(self):
        sb = Songbook.objects.create(
            slug="pub", title="Public", visibility=SongbookVisibility.PUBLIC,
        )
        self.assertTrue(can_access_songbook(self.alice, sb))
        self.assertTrue(can_access_songbook(self.bob, sb))

    def test_private_songbook_owner_only(self):
        sb = Songbook.objects.create(
            slug="priv", title="Private", owner=self.alice,
            visibility=SongbookVisibility.PRIVATE,
        )
        self.assertTrue(can_access_songbook(self.alice, sb))
        self.assertFalse(can_access_songbook(self.bob, sb))

    def test_private_songbook_accessible_via_share(self):
        sb = Songbook.objects.create(
            slug="priv", title="Private", owner=self.alice,
            visibility=SongbookVisibility.PRIVATE,
        )
        SongbookShare.objects.create(
            songbook=sb, sharer=self.alice, recipient=self.bob,
        )
        self.assertTrue(can_access_songbook(self.bob, sb))

    def test_studio_songbook_accessible_to_studio_members(self):
        studio = Studio.objects.create(
            slug="jam", name="Jam", owner=self.alice,
            visibility=StudioVisibility.PUBLIC,
        )
        StudioMember.objects.create(
            studio=studio, user=self.bob, role=StudioRole.MEMBER,
        )
        sb = Songbook.objects.create(
            slug="studio", title="Studio book", owner=self.alice,
            visibility=SongbookVisibility.STUDIO, studio=studio,
        )
        self.assertTrue(can_access_songbook(self.bob, sb))

    def test_studio_songbook_blocked_for_banned_member(self):
        studio = Studio.objects.create(
            slug="jam", name="Jam", owner=self.alice,
            visibility=StudioVisibility.PUBLIC,
        )
        StudioMember.objects.create(
            studio=studio, user=self.bob, role=StudioRole.BANNED,
        )
        sb = Songbook.objects.create(
            slug="studio", title="Studio book", owner=self.alice,
            visibility=SongbookVisibility.STUDIO, studio=studio,
        )
        self.assertFalse(can_access_songbook(self.bob, sb))

    def test_anonymous_no_access(self):
        sb = Songbook.objects.create(
            slug="pub", title="Public", visibility=SongbookVisibility.PUBLIC,
        )
        self.assertFalse(can_access_songbook(None, sb))


class SongbookShareModelTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        self.sb = Songbook.objects.create(
            slug="b", title="B", owner=self.alice,
        )

    def test_unique_recipient_per_songbook(self):
        SongbookShare.objects.create(
            songbook=self.sb, sharer=self.alice, recipient=self.bob,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SongbookShare.objects.create(
                songbook=self.sb, sharer=self.alice, recipient=self.bob,
            )


class SongbookListViewTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )

    def test_list_filters_by_accessibility(self):
        Songbook.objects.create(
            slug="pub", title="Pub", visibility=SongbookVisibility.PUBLIC,
        )
        Songbook.objects.create(
            slug="priv-alice", title="Alice's", owner=self.alice,
            visibility=SongbookVisibility.PRIVATE,
        )
        # Bob's: shouldn't see Alice's private
        self.client.force_login(self.bob)
        response = self.client.get(reverse("charts:songbook_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pub")
        self.assertNotContains(response, "Alice's")


class SongbookShareViewTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.bob = User.objects.create_user(
            username="bob", password=secrets.token_urlsafe(16),
        )
        self.sb = Songbook.objects.create(
            slug="b", title="B", owner=self.alice,
            visibility=SongbookVisibility.PRIVATE,
        )

    def test_owner_can_share(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("charts:songbook_share", args=[self.sb.pk]),
            {"recipient_lookup": "bob"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            SongbookShare.objects.filter(
                songbook=self.sb, recipient=self.bob,
            ).exists()
        )

    def test_non_owner_403(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("charts:songbook_share", args=[self.sb.pk]),
            {"recipient_lookup": "alice"},
        )
        self.assertEqual(response.status_code, 403)

    def test_self_share_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("charts:songbook_share", args=[self.sb.pk]),
            {"recipient_lookup": "alice"},
        )
        # Form re-redirects with error; no share created
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SongbookShare.objects.count(), 0)


class SongbookVisibilityToggleTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password=secrets.token_urlsafe(16),
        )
        self.sb = Songbook.objects.create(
            slug="b", title="B", owner=self.alice,
            visibility=SongbookVisibility.PRIVATE,
        )

    def test_owner_can_toggle(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("charts:songbook_visibility", args=[self.sb.pk]),
            {"visibility": "public"},
        )
        self.assertEqual(response.status_code, 302)
        self.sb.refresh_from_db()
        self.assertEqual(self.sb.visibility, SongbookVisibility.PUBLIC)

    def test_invalid_visibility_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("charts:songbook_visibility", args=[self.sb.pk]),
            {"visibility": "bogus"},
        )
        self.assertEqual(response.status_code, 302)
        self.sb.refresh_from_db()
        self.assertEqual(self.sb.visibility, SongbookVisibility.PRIVATE)
