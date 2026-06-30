"""Signal handlers for #196 — sync UserProfile.is_pedagogue to a
Wagtail Group named ``Pedagogue``.

Registered in ``apps.cms.apps.CmsConfig.ready()``. The Group itself
is created (with permissions) by the data migration
``0002_pedagogue_group``. This signal keeps Group membership in sync
when the role flips.

Failure mode this prevents: pedagogue role granted on UserProfile but
the user can't log into ``/cms/`` because their Wagtail Group
membership wasn't updated. The signal closes that gap.
"""

from __future__ import annotations

import logging

from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.models import UserProfile


PEDAGOGUE_GROUP_NAME = "Pedagogue"

log = logging.getLogger(__name__)


@receiver(post_save, sender=UserProfile)
def sync_pedagogue_wagtail_group(sender, instance, **kwargs):
    """Add / remove the user from the Pedagogue Wagtail Group.

    Pulls the initial value stashed by ``apps.core.signals``'s
    ``stash_initial_role_values`` post_init handler. If
    ``is_pedagogue`` flipped, mutate Group membership accordingly.
    """
    initial = getattr(instance, "_initial_role_values", None)
    if initial is None:
        # First load before post_init ran, or a no-pk save path. Defer
        # to the next save — keeps the signal idempotent without
        # forcing a Group lookup on every save call.
        return

    old = initial.get("is_pedagogue")
    new = instance.is_pedagogue
    if old == new:
        return

    try:
        group = Group.objects.get(name=PEDAGOGUE_GROUP_NAME)
    except Group.DoesNotExist:
        # Migration 0002 hasn't run yet — this can happen during the
        # initial migrate of a fresh DB. Don't break the migrate;
        # backfill in 0002 covers existing users at migrate time.
        log.warning(
            "Pedagogue Wagtail group missing; skipping membership sync "
            "for %s. Apply apps.cms migration 0002.",
            instance.user_id,
        )
        return

    if new:
        instance.user.groups.add(group)
    else:
        instance.user.groups.remove(group)
