from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from pages.views import profile_view


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/profile/", profile_view, name="account_profile"),
    path("accounts/", include("allauth.urls")),

    path("", include("pages.urls")),

]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [
        path("__debug__/", include(debug_toolbar.urls)),
    ] + urlpatterns
