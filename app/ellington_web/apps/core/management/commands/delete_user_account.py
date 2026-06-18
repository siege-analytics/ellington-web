"""Delete a user account — hard-delete personal artifacts, anonymize
ground-truth artifacts to the sentinel user, log to
``AccountDeletionAudit``.

Per epic #96 sub-ticket (a):

- ``Goal`` rows cascade-delete with the User (already configured in the
  model). We just count them for the audit log before the User goes.
- The ``UserProfile`` cascade-deletes too.
- ``Comment`` / engine-rule ``Response`` artifacts (when those models
  land in #98 and sub-ticket d) are repointed to the sentinel user via
  the registered ``ANONYMIZE_REGISTRY`` below. v1 ships with the
  registry empty — the wiring is in place for sub-ticket (d) and #98
  to register their models without touching this command.

Usage:

    manage.py delete_user_account <username> --initiated-by <admin-username>

Both flags required. Wrapped in a single transaction so a failure
mid-anonymize doesn't leave half-anonymized rows behind.
"""

from __future__ import annotations

from typing import Callable

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.core.deletion import perform_account_deletion
from apps.core.models import DELETED_USER_USERNAME


# Registry of (artifact_name, callable) pairs. Each callable takes the
# user being deleted + the sentinel user, repoints the FK, and returns
# the count of rows touched. Sub-tickets (d) Comments and #98 Response
# register their models here when they land.
#
# Signature: callable(user, sentinel) -> int
ANONYMIZE_REGISTRY: list[tuple[str, Callable]] = []


class Command(BaseCommand):
    help = "Delete a user account — anonymize ground-truth, hard-delete personal artifacts, audit-log."

    def add_arguments(self, parser):
        parser.add_argument(
            "username",
            help="Username of the account to delete.",
        )
        parser.add_argument(
            "--initiated-by",
            required=True,
            help="Username of the admin initiating the deletion (for audit log).",
        )

    def handle(self, *args, **options):
        username = options["username"]
        admin_username = options["initiated_by"]

        if username == DELETED_USER_USERNAME:
            raise CommandError(
                f"Refusing to delete the sentinel user ({DELETED_USER_USERNAME})."
            )

        User = get_user_model()
        try:
            target = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"user not found: {username}")

        try:
            admin = User.objects.get(username=admin_username)
        except User.DoesNotExist:
            raise CommandError(f"--initiated-by user not found: {admin_username}")

        if not admin.is_staff:
            raise CommandError(
                f"--initiated-by user {admin_username} is not staff;"
                " only staff users may initiate account deletion."
            )

        try:
            audit = perform_account_deletion(target, initiated_by=admin)
        except ValueError as exc:
            raise CommandError(str(exc))

        counts = audit.anonymized_artifact_counts
        other = {
            k: v for k, v in counts.items()
            if k not in ("goals_deleted", "profile_deleted")
        }
        self.stdout.write(self.style.SUCCESS(
            f"deleted {username}:"
            f" goals={counts.get('goals_deleted', 0)}"
            f" profile={counts.get('profile_deleted', 0)}"
            f" anonymized={other}"
        ))
