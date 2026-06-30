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


class PreflightCheckTests(TestCase):
    """preflight_check exits 0 when migrations applied, non-zero
    when pending."""

    def test_exits_zero_when_no_pending(self):
        # In test setup migrations are applied, so the plan should be empty.
        try:
            call_command("preflight_check")
        except SystemExit as exc:
            self.fail(
                f"preflight_check should exit 0 in a fully-migrated test "
                f"DB, raised SystemExit({exc.code}) instead."
            )

    def test_verbose_success_prints_ok(self):
        from io import StringIO
        out = StringIO()
        call_command("preflight_check", "--verbose", stdout=out)
        self.assertIn("preflight ok", out.getvalue())

    def test_exits_nonzero_when_pending(self):
        """Simulate a pending migration by patching the migration_plan."""
        from unittest.mock import MagicMock, patch
        from django.db.migrations.migration import Migration

        fake_migration = MagicMock(spec=Migration)
        fake_migration.app_label = "fake_app"
        fake_migration.name = "0099_fake"

        plan = [(fake_migration, False)]

        with patch(
            "django.db.migrations.executor.MigrationExecutor.migration_plan",
            return_value=plan,
        ):
            with self.assertRaises(SystemExit) as cm:
                call_command("preflight_check")
            self.assertEqual(cm.exception.code, 1)

    def test_pending_migration_named_in_verbose(self):
        from io import StringIO
        from unittest.mock import MagicMock, patch
        from django.db.migrations.migration import Migration

        fake = MagicMock(spec=Migration)
        fake.app_label = "fake_app"
        fake.name = "0099_fake"
        err = StringIO()

        with patch(
            "django.db.migrations.executor.MigrationExecutor.migration_plan",
            return_value=[(fake, False)],
        ):
            with self.assertRaises(SystemExit):
                call_command("preflight_check", "--verbose", stderr=err)

        self.assertIn("fake_app.0099_fake", err.getvalue())
