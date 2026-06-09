from django.conf import settings
from django.contrib.auth.middleware import RemoteUserMiddleware


class AuthentikHeaderMiddleware(RemoteUserMiddleware):
    """Trust the X-authentik-* headers forwarded by the Authentik outpost.

    Sits after AuthenticationMiddleware in MIDDLEWARE. On each request:
      1. Read `X-authentik-username` from request.META.
      2. Hand it to `django.contrib.auth.authenticate(request, remote_user=...)`.
      3. The companion AuthentikRemoteUserBackend reads the rest of the
         X-authentik-* headers off `request.META` to sync email, name,
         groups, and is_superuser.

    Gated by settings.AUTHENTIK_HEADER_TRUST. Defaults False — local dev
    without Authentik in front does NOT trust headers, so a curl with
    --header 'X-authentik-username: akadmin' against runserver won't log
    you in. Production deploy sets AUTHENTIK_HEADER_TRUST=True via env.
    """

    header = "HTTP_X_AUTHENTIK_USERNAME"
    force_logout_if_no_header = True

    def process_request(self, request):
        if not getattr(settings, "AUTHENTIK_HEADER_TRUST", False):
            return
        return super().process_request(request)
