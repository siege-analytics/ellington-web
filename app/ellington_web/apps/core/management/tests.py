from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


User = get_user_model()


class EnsureSuperuserTests(TestCase):
    env = {
        "ADMIN_USERNAME": "dheeraj",
        "ADMIN_EMAIL": "dheeraj@elect.info",
        "ADMIN_PASSWORD": "very-good-password",
    }

    def _run(self, env=None):
        with mock.patch.dict("os.environ", env or self.env, clear=False):
            call_command("ensure_superuser")

    def test_creates_superuser_when_absent(self):
        self._run()
        user = User.objects.get(username="dheeraj")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertEqual(user.email, "dheeraj@elect.info")
        self.assertTrue(user.check_password("very-good-password"))

    def test_idempotent_no_password_reset(self):
        self._run()
        user = User.objects.get(username="dheeraj")
        original_pw_hash = user.password
        # Re-run with a different ADMIN_PASSWORD value — must NOT rotate the stored hash.
        self._run(env={**self.env, "ADMIN_PASSWORD": "different-password"})
        user.refresh_from_db()
        self.assertEqual(user.password, original_pw_hash)
        self.assertTrue(user.check_password("very-good-password"))
        self.assertFalse(user.check_password("different-password"))

    def test_promotes_existing_non_superuser(self):
        User.objects.create_user(
            username="dheeraj",
            email="old@elect.info",
            password="legacy-password",
        )
        self._run()
        user = User.objects.get(username="dheeraj")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertEqual(user.email, "dheeraj@elect.info")
        # Password from the pre-existing account is preserved.
        self.assertTrue(user.check_password("legacy-password"))

    def test_missing_env_raises(self):
        for missing in ("ADMIN_USERNAME", "ADMIN_EMAIL", "ADMIN_PASSWORD"):
            env = {**self.env, missing: ""}
            with self.subTest(missing=missing), self.assertRaises(CommandError) as ctx:
                self._run(env=env)
            self.assertIn(missing, str(ctx.exception))
