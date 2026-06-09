from django.contrib.auth import get_user_model
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase, override_settings

from apps.core.auth.backends import AUTHENTIK_ADMINS_GROUP, AuthentikRemoteUserBackend
from apps.core.auth.middleware import AuthentikHeaderMiddleware


User = get_user_model()


def _prepare(request):
    """Run SessionMiddleware + AuthenticationMiddleware so request.user / session exist."""
    SessionMiddleware(lambda r: None).process_request(request)
    AuthenticationMiddleware(lambda r: None).process_request(request)
    return request


@override_settings(
    AUTHENTIK_HEADER_TRUST=True,
    AUTHENTICATION_BACKENDS=["apps.core.auth.backends.AuthentikRemoteUserBackend"],
)
class AuthentikHeaderMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = AuthentikHeaderMiddleware(lambda r: None)

    def _request(self, **headers):
        request = self.factory.get("/", **headers)
        _prepare(request)
        return request

    def test_new_user_created_from_headers(self):
        request = self._request(
            HTTP_X_AUTHENTIK_USERNAME="dheeraj@elect.info",
            HTTP_X_AUTHENTIK_EMAIL="dheeraj@elect.info",
            HTTP_X_AUTHENTIK_NAME="Dheeraj Chand",
            HTTP_X_AUTHENTIK_GROUPS="users",
        )
        self.middleware(request)
        self.assertTrue(request.user.is_authenticated)
        self.assertEqual(request.user.username, "dheeraj@elect.info")
        self.assertEqual(request.user.email, "dheeraj@elect.info")
        self.assertEqual(request.user.first_name, "Dheeraj")
        self.assertEqual(request.user.last_name, "Chand")
        self.assertFalse(request.user.is_superuser)
        self.assertEqual({g.name for g in request.user.groups.all()}, {"users"})

    def test_returning_user_email_and_groups_resync(self):
        user = User.objects.create(
            username="dheeraj@elect.info",
            email="old@elect.info",
            first_name="Old",
        )
        existing_group = Group.objects.create(name="stale-group")
        user.groups.add(existing_group)

        request = self._request(
            HTTP_X_AUTHENTIK_USERNAME="dheeraj@elect.info",
            HTTP_X_AUTHENTIK_EMAIL="dheeraj@elect.info",
            HTTP_X_AUTHENTIK_NAME="Dheeraj Chand",
            HTTP_X_AUTHENTIK_GROUPS="users|engineering",
        )
        self.middleware(request)

        user.refresh_from_db()
        self.assertEqual(user.email, "dheeraj@elect.info")
        self.assertEqual(user.first_name, "Dheeraj")
        self.assertEqual({g.name for g in user.groups.all()}, {"users", "engineering"})

    def test_authentik_admins_group_grants_superuser(self):
        request = self._request(
            HTTP_X_AUTHENTIK_USERNAME="dheeraj@elect.info",
            HTTP_X_AUTHENTIK_GROUPS=f"users|{AUTHENTIK_ADMINS_GROUP}",
        )
        self.middleware(request)
        self.assertTrue(request.user.is_superuser)
        self.assertTrue(request.user.is_staff)

    def test_superuser_revoked_when_group_removed(self):
        user = User.objects.create(
            username="ex-admin@elect.info",
            is_superuser=True,
            is_staff=True,
        )
        request = self._request(
            HTTP_X_AUTHENTIK_USERNAME="ex-admin@elect.info",
            HTTP_X_AUTHENTIK_GROUPS="users",
        )
        self.middleware(request)
        user.refresh_from_db()
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)

    def test_no_username_header_leaves_request_anonymous(self):
        request = self._request()
        self.middleware(request)
        self.assertIsInstance(request.user, AnonymousUser)


@override_settings(
    AUTHENTIK_HEADER_TRUST=False,
    AUTHENTICATION_BACKENDS=["apps.core.auth.backends.AuthentikRemoteUserBackend"],
)
class AuthentikHeaderTrustOptInTests(TestCase):
    """When AUTHENTIK_HEADER_TRUST is False, spoofed headers must NOT log in."""

    def test_spoofed_headers_ignored_when_trust_disabled(self):
        factory = RequestFactory()
        middleware = AuthentikHeaderMiddleware(lambda r: None)
        request = factory.get(
            "/",
            HTTP_X_AUTHENTIK_USERNAME="attacker@elsewhere.com",
            HTTP_X_AUTHENTIK_EMAIL="attacker@elsewhere.com",
            HTTP_X_AUTHENTIK_GROUPS=AUTHENTIK_ADMINS_GROUP,
        )
        _prepare(request)
        middleware(request)
        self.assertIsInstance(request.user, AnonymousUser)
        self.assertFalse(User.objects.filter(username="attacker@elsewhere.com").exists())
