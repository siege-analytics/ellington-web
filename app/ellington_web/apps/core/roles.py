"""Role helpers — single seam for role checks across the app.

Every view, serializer, decorator, and DRF permission that asks "is
this user a Pedagogue / Admin?" goes through here, not through
``user.profile.is_pedagogue`` directly. When sub-ticket (b) eventually
adds object-level perms (``django-guardian``) or migrates to Django
Groups, only this module changes — call sites stay put.

Per epic #96 (sub-ticket a): Pedagogue is a stackable side-role, Admin
is ``User.is_staff``, General is the absence of both.
"""

from __future__ import annotations

from functools import wraps
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseForbidden
from rest_framework.permissions import BasePermission


def is_pedagogue(user) -> bool:
    """True if user has the Pedagogue side-role set on their profile.

    Anonymous users return False. Authenticated users without a profile
    (e.g. the bootstrap superuser before first admin login) return
    False — Pedagogue is opt-in via admin toggle.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    try:
        profile = user.profile
    except ObjectDoesNotExist:
        return False
    return bool(profile.is_pedagogue)


def is_admin(user) -> bool:
    """True if user is a Django staff user (the Admin tier).

    Delegates to ``User.is_staff``. ``is_superuser`` implies
    ``is_staff`` in Django, so superusers also pass.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_staff", False))


class IsPedagogue(BasePermission):
    """DRF permission class — request.user must be a Pedagogue."""

    message = "Pedagogue role required."

    def has_permission(self, request, view) -> bool:
        return is_pedagogue(request.user)


class IsAdmin(BasePermission):
    """DRF permission class — request.user must be an Admin (is_staff)."""

    message = "Admin role required."

    def has_permission(self, request, view) -> bool:
        return is_admin(request.user)


def pedagogue_required(view_func):
    """Django view decorator — 403 if request.user is not a Pedagogue.

    Use on plain Django views (not DRF). For DRF, use ``IsPedagogue``.
    """

    @wraps(view_func)
    def _wrapped(request, *args: Any, **kwargs: Any):
        if not is_pedagogue(request.user):
            return HttpResponseForbidden("Pedagogue role required.")
        return view_func(request, *args, **kwargs)

    return _wrapped


__all__ = [
    "IsAdmin",
    "IsPedagogue",
    "is_admin",
    "is_pedagogue",
    "pedagogue_required",
]
