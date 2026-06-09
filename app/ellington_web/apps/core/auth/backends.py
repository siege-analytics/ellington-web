from django.contrib.auth.backends import RemoteUserBackend
from django.contrib.auth.models import Group


AUTHENTIK_ADMINS_GROUP = "authentik Admins"


def _parse_groups(raw):
    """X-authentik-groups is pipe-separated. Empty string → []."""
    if not raw:
        return []
    return [g.strip() for g in raw.split("|") if g.strip()]


class AuthentikRemoteUserBackend(RemoteUserBackend):
    """Companion backend for AuthentikHeaderMiddleware.

    On successful authentication, syncs the User record from the rest of
    the X-authentik-* headers on `request.META`:
      X-authentik-email   → user.email
      X-authentik-name    → user.first_name + user.last_name (split on first space)
      X-authentik-groups  → Django Group memberships; presence of
                            'authentik Admins' → user.is_superuser

    User membership in Groups is replaced wholesale on every request — if
    Authentik says you're in [A, B], any other Group on the User in Django
    gets unbound. This matches Authentik's source-of-truth role.
    """

    create_unknown_user = True

    def authenticate(self, request, remote_user=None):
        user = super().authenticate(request, remote_user)
        if user is None or request is None:
            return user
        self._sync_from_headers(user, request.META)
        return user

    def configure_user(self, request, user, created=True):
        # Called by super().authenticate when a new user is created.
        if request is not None:
            self._sync_from_headers(user, request.META)
        return user

    def _sync_from_headers(self, user, meta):
        email = meta.get("HTTP_X_AUTHENTIK_EMAIL", "").strip()
        name = meta.get("HTTP_X_AUTHENTIK_NAME", "").strip()
        groups = _parse_groups(meta.get("HTTP_X_AUTHENTIK_GROUPS", ""))

        dirty = False
        if email and user.email != email:
            user.email = email
            dirty = True

        if name:
            first, _, last = name.partition(" ")
            if user.first_name != first:
                user.first_name = first
                dirty = True
            if user.last_name != last:
                user.last_name = last
                dirty = True

        should_be_superuser = AUTHENTIK_ADMINS_GROUP in groups
        if user.is_superuser != should_be_superuser:
            user.is_superuser = should_be_superuser
            user.is_staff = should_be_superuser
            dirty = True

        if dirty:
            user.save()

        # Group sync — replace, don't merge.
        desired = []
        for name in groups:
            group, _ = Group.objects.get_or_create(name=name)
            desired.append(group)
        user.groups.set(desired)
