"""Test settings — minimal, no PostGIS, no celery/grappelli/redis side effects.

Used by `manage.py test --settings=ellington_web.test_settings`. Builds a
hand-rolled minimum Django config rather than chaining through
settings/__init__.py — the GST star-import order has a known bug where
logging.py references settings.LOGS_DIRECTORY before path_settings has
populated it (manifests only during cold loads outside docker).

When sub-2c lands the proper DB story and sub-2e settles the runtime, this
can be replaced by a wrapper around the production settings module.
"""

SECRET_KEY = "test-only-not-secret"  # noqa: S105
DEBUG = False
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.styles",
    "apps.charts",
    "apps.practice",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.auth.middleware.AuthentikHeaderMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "apps.core.auth.backends.AuthentikRemoteUserBackend",
    "django.contrib.auth.backends.ModelBackend",
]

ROOT_URLCONF = "ellington_web.test_urls"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Disable header trust by default in tests; the trust-on TestCases use
# override_settings to flip it.
AUTHENTIK_HEADER_TRUST = False

USE_TZ = True
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
