"""Signal handlers for role-change audits (epic #96 sub-ticket j / #131).

Connected in apps.core.apps.CoreConfig.ready(). Watches UserProfile
field flips and writes RolePromotionAudit rows.
"""

from __future__ import annotations

from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from .middleware import get_current_user
from .models import RolePromotionAudit, UserProfile


# Track the audited fields. Add new keys here as more role flags appear.
AUDITED_FIELDS = ("is_pedagogue",)


@receiver(post_init, sender=UserProfile)
def stash_initial_role_values(sender, instance, **kwargs):
    """Stash the initial values of audited fields so post_save can diff."""
    initial = {}
    for field in AUDITED_FIELDS:
        # Only stash when the instance is loaded from DB (pk set).
        if instance.pk is not None:
            initial[field] = getattr(instance, field)
    instance._initial_role_values = initial


@receiver(post_save, sender=UserProfile)
def audit_role_changes(sender, instance, created, **kwargs):
    """Diff against the stashed initial values and write audit rows."""
    if created:
        # Initial creation isn't a "promotion" — only changes are audited.
        return

    initial = getattr(instance, "_initial_role_values", None)
    if not initial:
        return

    current_user = get_current_user()
    promoted_by_username = (
        getattr(current_user, "username", "") or "system"
    )

    for field in AUDITED_FIELDS:
        if field not in initial:
            continue
        old_val = initial[field]
        new_val = getattr(instance, field)
        if old_val == new_val:
            continue

        RolePromotionAudit.objects.create(
            target_user=instance.user,
            target_username=instance.user.username,
            promoted_by=current_user if getattr(
                current_user, "is_authenticated", False,
            ) else None,
            promoted_by_username=promoted_by_username,
            field_name=field,
            old_value=bool(old_val),
            new_value=bool(new_val),
        )

    # Re-stash after writing so consecutive saves in the same request
    # don't double-fire.
    instance._initial_role_values = {
        field: getattr(instance, field) for field in AUDITED_FIELDS
    }
