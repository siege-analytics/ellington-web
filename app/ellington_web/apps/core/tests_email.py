"""Tests for email plumbing — send_test_email + password reset templates.

We don't actually hit DreamHost in tests; Django's
``locmem`` email backend captures sent messages in ``mail.outbox`` for
assertion.
"""

from __future__ import annotations

import secrets
from io import StringIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings


User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="dheeraj@dheerajchand.com",
    REPLY_TO_EMAIL="dheeraj.chand@gmail.com",
    EMAIL_HOST="smtp.dreamhost.com",
    EMAIL_PORT=587,
)
class SendTestEmailTests(TestCase):
    def setUp(self):
        mail.outbox = []

    def test_sends_one_message(self):
        call_command("send_test_email", "steve@blackmon.org", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)

    def test_envelope_shape(self):
        call_command("send_test_email", "steve@blackmon.org", stdout=StringIO())
        msg = mail.outbox[0]
        self.assertEqual(msg.from_email, "dheeraj@dheerajchand.com")
        self.assertEqual(msg.to, ["steve@blackmon.org"])
        self.assertEqual(msg.reply_to, ["dheeraj.chand@gmail.com"])
        self.assertEqual(msg.subject, "Ellington email plumbing OK")
        self.assertIn("smtp.dreamhost.com", msg.body)

    def test_rejects_non_email_argument(self):
        with self.assertRaises(CommandError):
            call_command("send_test_email", "not-an-email", stdout=StringIO())


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="dheeraj@dheerajchand.com",
)
class PasswordResetTemplateTests(TestCase):
    """The Django built-in PasswordResetView picks up our templates from
    ``apps/core/templates/registration/``. Verify Ellington branding
    is in the rendered email body."""

    def setUp(self):
        mail.outbox = []
        # secrets.token_urlsafe avoids hardcoded-password false positives
        # from secret scanners; the password text isn't asserted on.
        self.user = User.objects.create_user(
            username="trevor",
            email="trevor@example.com",
            password=secrets.token_urlsafe(16),
        )

    def test_password_reset_email_uses_ellington_subject(self):
        response = self.client.post(
            "/accounts/password_reset/",
            {"email": "trevor@example.com"},
        )
        self.assertIn(response.status_code, (302, 200))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Ellington", mail.outbox[0].subject)

    def test_password_reset_body_mentions_username(self):
        self.client.post(
            "/accounts/password_reset/",
            {"email": "trevor@example.com"},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("trevor", mail.outbox[0].body)
