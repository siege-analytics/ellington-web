"""Tests for apps.core models — UserProfile + Goal.

The auth-side tests (RemoteUserBackend, header middleware) live in
apps/core/auth/tests.py. The management-command tests
(ensure_superuser) live in apps/core/management/tests.py. This file
covers the new model layer added by #46.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.core.models import (
    Goal,
    GoalStatus,
    Instrument,
    SkillLevel,
    UserProfile,
)
from apps.styles.models import Idiom, Master, Style


User = get_user_model()


class UserProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="dheeraj")

    def test_one_to_one_with_user(self):
        UserProfile.objects.create(user=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            UserProfile.objects.create(user=self.user)

    def test_default_instrument_guitar_skill_intermediate(self):
        p = UserProfile.objects.create(user=self.user)
        self.assertEqual(p.instrument, Instrument.GUITAR)
        self.assertEqual(p.skill_level, SkillLevel.INTERMEDIATE)
        self.assertEqual(p.timezone, "UTC")

    def test_preferred_m2ms_default_empty(self):
        p = UserProfile.objects.create(user=self.user)
        self.assertEqual(p.preferred_styles.count(), 0)
        self.assertEqual(p.preferred_idioms.count(), 0)
        self.assertEqual(p.preferred_masters.count(), 0)

    def test_can_attach_preferred_styles_idioms_masters(self):
        p = UserProfile.objects.create(user=self.user)
        bebop = Style.objects.create(slug="bebop", name="Bebop")
        cm = Idiom.objects.create(slug="chord-melody", name="Chord Melody")
        pass_m = Master.objects.create(slug="joe-pass", name="Joe Pass")
        p.preferred_styles.add(bebop)
        p.preferred_idioms.add(cm)
        p.preferred_masters.add(pass_m)
        self.assertEqual(list(p.preferred_styles.values_list("slug", flat=True)), ["bebop"])
        self.assertEqual(list(p.preferred_idioms.values_list("slug", flat=True)), ["chord-melody"])
        self.assertEqual(list(p.preferred_masters.values_list("slug", flat=True)), ["joe-pass"])

    def test_profile_cascades_on_user_delete(self):
        UserProfile.objects.create(user=self.user)
        self.user.delete()
        self.assertEqual(UserProfile.objects.count(), 0)

    def test_user_can_exist_without_profile(self):
        # Profile is created lazily; user.profile doesn't exist by default
        from django.core.exceptions import ObjectDoesNotExist
        with self.assertRaises(ObjectDoesNotExist):
            _ = self.user.profile


class GoalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="dheeraj")
        self.bebop = Style.objects.create(slug="bebop", name="Bebop")
        self.cm = Idiom.objects.create(slug="chord-melody", name="Chord Melody")
        self.pass_m = Master.objects.create(slug="joe-pass", name="Joe Pass")

    def test_goal_can_target_just_style(self):
        g = Goal.objects.create(user=self.user, title="Learn jazz", target_style=self.bebop)
        self.assertEqual(g.status, GoalStatus.ACTIVE)
        self.assertIsNone(g.target_idiom_id)
        self.assertIsNone(g.target_master_id)

    def test_goal_can_target_all_three_axes(self):
        g = Goal.objects.create(
            user=self.user,
            title="Sound like Joe Pass on chord-melody",
            target_master=self.pass_m,
            target_style=self.bebop,
            target_idiom=self.cm,
            target_completion_date=date(2027, 1, 1),
        )
        self.assertEqual(g.target_master.slug, "joe-pass")
        self.assertEqual(g.target_style.slug, "bebop")
        self.assertEqual(g.target_idiom.slug, "chord-melody")

    def test_goal_cascades_on_user_delete(self):
        Goal.objects.create(user=self.user, title="goal 1")
        Goal.objects.create(user=self.user, title="goal 2")
        self.user.delete()
        self.assertEqual(Goal.objects.count(), 0)

    def test_targets_SET_NULL_on_delete(self):
        g = Goal.objects.create(
            user=self.user, title="learn bebop", target_style=self.bebop,
        )
        self.bebop.delete()
        g.refresh_from_db()
        self.assertIsNone(g.target_style)

    def test_goal_status_transitions(self):
        g = Goal.objects.create(user=self.user, title="goal")
        g.status = GoalStatus.PAUSED
        g.save()
        g.refresh_from_db()
        self.assertEqual(g.status, GoalStatus.PAUSED)
        g.status = GoalStatus.ACHIEVED
        g.save()
        g.refresh_from_db()
        self.assertEqual(g.status, GoalStatus.ACHIEVED)


class EndToEndTests(TestCase):
    """One user, one profile, two goals targeting different axes,
    preferred styles/idioms/masters attached."""

    def test_full_chain(self):
        user = User.objects.create(username="dheeraj")
        profile = UserProfile.objects.create(
            user=user,
            display_name="Dheeraj Chand",
            instrument=Instrument.GUITAR,
            skill_level=SkillLevel.ADVANCED,
            timezone="America/Chicago",
        )
        # M2Ms
        bebop = Style.objects.create(slug="bebop", name="Bebop")
        bossa = Style.objects.create(slug="bossa-nova", name="Bossa Nova")
        cm = Idiom.objects.create(slug="chord-melody", name="Chord Melody")
        pass_m = Master.objects.create(slug="joe-pass", name="Joe Pass")
        van_eps = Master.objects.create(slug="van-eps", name="George Van Eps")
        profile.preferred_styles.add(bebop, bossa)
        profile.preferred_idioms.add(cm)
        profile.preferred_masters.add(pass_m, van_eps)

        # Goals
        Goal.objects.create(
            user=user, title="Chord-melody fluency",
            target_master=pass_m, target_idiom=cm,
        )
        Goal.objects.create(
            user=user, title="Bossa swing-feel control",
            target_style=bossa,
        )

        # Reverse traversal — most useful pattern for the eventual
        # default-suggestion mode
        self.assertEqual(user.profile.preferred_styles.count(), 2)
        self.assertEqual(user.goals.count(), 2)
        # Reach into one goal's targets
        chord_melody_goal = user.goals.get(title="Chord-melody fluency")
        self.assertEqual(chord_melody_goal.target_master.slug, "joe-pass")
        self.assertEqual(chord_melody_goal.target_idiom.slug, "chord-melody")
