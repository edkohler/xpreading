from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.decorators.cache import cache_page

from pages.sitemaps import sitemaps
from pages.views import profile_view, robots_txt

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "sitemap.xml",
        cache_page(60 * 60 * 6)(sitemap),
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("robots.txt", robots_txt, name="robots_txt"),
    path("accounts/profile/", profile_view, name="account_profile"),
    path("accounts/", include("allauth.urls")),
    path("", include("pages.urls")),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [
        path("__debug__/", include(debug_toolbar.urls)),
    ] + urlpatterns
