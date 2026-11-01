from django.conf import settings
from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.masters.urls")),
    path("api/v1/", include("apps.accounting.urls")),
    path("api/v1/", include("apps.vouchers.urls")),
    path("api/v1/", include("apps.payments.urls")),
    path("api/v1/", include("apps.sales.urls")),
    path("api/v1/", include("apps.inventory.urls")),
]

# Django's built-in admin signs in with a password only (no two-factor), so it is available
# on developers' machines but never on the test or production servers.
if settings.DEBUG:
    from django.contrib import admin

    urlpatterns.insert(0, path("admin/", admin.site.urls))
