"""Idempotently ensure a Django superuser exists, sourced from env.

Designed for k8s Job invocation where ADMIN_USERNAME / ADMIN_EMAIL /
ADMIN_PASSWORD come from a Secret via envFrom. Re-running is safe:
existing users get email/is_superuser/is_staff updated, but their
password is NEVER reset by this command.

The intentional asymmetry — create-with-password but never-update-
password — keeps the bootstrap recipe replayable without surprising
the human whose account it is. Password rotation should happen via
`manage.py changepassword` or the Authentik header-sync path, not by
re-running this Job.
"""

import os
import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Idempotently create or update a Django superuser from env vars."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME", "").strip()
        email = os.environ.get("ADMIN_EMAIL", "").strip()
        password = os.environ.get("ADMIN_PASSWORD", "")

        missing = [
            name for name, value in (
                ("ADMIN_USERNAME", username),
                ("ADMIN_EMAIL", email),
                ("ADMIN_PASSWORD", password),
            ) if not value
        ]
        if missing:
            raise CommandError(f"missing required env: {', '.join(missing)}")

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email},
        )

        if created:
            user.set_password(password)
            user.email = email
            user.is_superuser = True
            user.is_staff = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"created superuser {username}"))
            return

        # Existing user — sync email + flags, NEVER reset password.
        dirty = False
        if user.email != email:
            user.email = email
            dirty = True
        if not user.is_superuser:
            user.is_superuser = True
            dirty = True
        if not user.is_staff:
            user.is_staff = True
            dirty = True
        if dirty:
            user.save()
            self.stdout.write(self.style.SUCCESS(
                f"updated existing user {username} (email/flags only — password unchanged)"
            ))
        else:
            self.stdout.write(f"user {username} already a superuser — no change")
