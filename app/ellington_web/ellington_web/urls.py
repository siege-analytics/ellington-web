"""
URL configuration for ellington_web project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include


urlpatterns = [
    path("grappelli/", include("grappelli.urls")),  # Grappelli URLs
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.core.urls")),  # invite/<token>/ before django.contrib.auth
    path("accounts/", include("django.contrib.auth.urls")),  # Django auth URLs
    path("api-auth/", include("rest_framework.urls")),
    path("locations/", include("locations.urls")),
    path("critique/", include("apps.styles.urls")),
    path("practice/", include("apps.practice.urls")),
    path("charts/", include("apps.charts.urls")),
]

# In dev, Daphne serves user-uploaded recordings from MEDIA_ROOT. In
# production this URL is fronted by the deployment's static file server
# (Nginx/CDN), so the helper is a no-op when DEBUG=False.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
