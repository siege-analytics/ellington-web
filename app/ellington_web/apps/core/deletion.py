"""Reusable account-deletion core (epic #96 sub-tickets a + k / #100 + #112).

The flow itself — anonymize ground-truth artifacts, hard-delete personal
artifacts, write an AccountDeletionAudit row — is one function that
both the admin management command (``delete_user_account``) and the
self-service view (`/accounts/delete/` per #112) share. Keeping this
in a stand-alone module avoids import cycles between
`management.commands.*` and `views.*`.

Per epic #96 sub-ticket (a): personal artifacts (Goals, the
UserProfile) cascade-delete with the User; ground-truth artifacts
(comments, engine-rule responses) are repointed via the
`ANONYMIZE_REGISTRY` so threads + ground-truth verdicts survive.
The registry lives in
`apps.core.management.commands.delete_user_account` for now —
sub-tickets (d)/(e)/(#98) register their models there at app-ready
time.
"""

from __future__ import annotations

from typing import Mapping

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import (
    AccountDeletionAudit,
    DELETED_USER_USERNAME,
    Goal,
    UserProfile,
    get_or_create_deleted_user_sentinel,
)


User = get_user_model()


@transaction.atomic
def perform_account_deletion(
    user_to_delete,
    initiated_by,
) -> AccountDeletionAudit:
    """Delete a user account end-to-end.

    Raises ``ValueError`` for refused inputs (sentinel deletion,
    user_to_delete == sentinel, missing initiated_by, etc.) — the
    caller decides whether to surface as CommandError (admin path)
    or 4xx (self-service view).
    """
    if user_to_delete is None or initiated_by is None:
        raise ValueError("user_to_delete and initiated_by are required")

    if user_to_delete.username == DELETED_USER_USERNAME:
        raise ValueError(
            f"Refusing to delete the sentinel user ({DELETED_USER_USERNAME})."
        )

    sentinel = get_or_create_deleted_user_sentinel()
    if user_to_delete.pk == sentinel.pk:
        raise ValueError("Refusing to delete the sentinel user.")

    # Snapshot username before delete clears the row
    username_snapshot = user_to_delete.username

    # Count cascade-deletes BEFORE delete (we lose the rows after).
    goals_count = Goal.objects.filter(user=user_to_delete).count()
    profile_count = UserProfile.objects.filter(user=user_to_delete).count()

    # Run anonymize callbacks lazily — import here to avoid the cycle
    # described in the module docstring.
    from apps.core.management.commands.delete_user_account import (
        ANONYMIZE_REGISTRY,
    )

    anonymized: dict[str, int] = {}
    for artifact_name, repoint in ANONYMIZE_REGISTRY:
        anonymized[artifact_name] = repoint(user_to_delete, sentinel)

    # Snapshot the initiator's identity BEFORE the delete in case
    # initiated_by IS user_to_delete (self-delete path) — after delete()
    # the instance is stale.
    initiator_username = initiated_by.username
    is_self_delete = initiated_by.pk == user_to_delete.pk

    # Hard-delete the user. Cascades to UserProfile + Goal + anything
    # else with on_delete=CASCADE pointing at User.
    user_to_delete.delete()

    return AccountDeletionAudit.objects.create(
        deleted_username=username_snapshot,
        initiated_by_username=initiator_username,
        # For self-delete the FK would dangle — leave it null and rely
        # on initiated_by_username for the audit trail. For admin-delete
        # the admin row is still alive so the FK points to a real row.
        deleted_by=None if is_self_delete else initiated_by,
        anonymized_artifact_counts={
            "goals_deleted": goals_count,
            "profile_deleted": profile_count,
            **anonymized,
        },
    )


__all__ = ["perform_account_deletion"]
