from django.urls import path

from . import access_views, audit_views, auth_views, organisation_views, views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("auth/csrf/", auth_views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/login/", auth_views.LoginView.as_view(), name="auth-login"),
    path("auth/login/verify/", auth_views.LoginVerifyView.as_view(), name="auth-login-verify"),
    path("auth/logout/", auth_views.LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", auth_views.MeView.as_view(), name="auth-me"),
    path("auth/two-factor/setup/", auth_views.TwoFactorSetupView.as_view(), name="auth-2fa-setup"),
    path(
        "auth/two-factor/confirm/",
        auth_views.TwoFactorConfirmView.as_view(),
        name="auth-2fa-confirm",
    ),
    path(
        "auth/password/change/",
        auth_views.PasswordChangeView.as_view(),
        name="auth-password-change",
    ),
    path("auth/login-history/", auth_views.LoginHistoryView.as_view(), name="auth-login-history"),
    path("access/catalog/", access_views.CatalogView.as_view(), name="access-catalog"),
    path("divisions/", access_views.DivisionListView.as_view(), name="division-list"),
    path(
        "divisions/<str:code>/", access_views.DivisionDetailView.as_view(), name="division-detail"
    ),
    path("company/", organisation_views.CompanyView.as_view(), name="company"),
    path("company/logo/", organisation_views.CompanyLogoView.as_view(), name="company-logo"),
    path(
        "settings/divisions/",
        organisation_views.DivisionAdminListView.as_view(),
        name="settings-division-list",
    ),
    path(
        "settings/divisions/<int:pk>/",
        organisation_views.DivisionAdminDetailView.as_view(),
        name="settings-division-detail",
    ),
    path("roles/", access_views.RoleListView.as_view(), name="role-list"),
    path("roles/<slug:code>/", access_views.RoleDetailView.as_view(), name="role-detail"),
    path("users/", access_views.UserListView.as_view(), name="user-list"),
    path("users/<int:pk>/", access_views.UserDetailView.as_view(), name="user-detail"),
    path("users/<int:pk>/roles/", access_views.UserRolesView.as_view(), name="user-roles"),
    path("users/<int:pk>/scope/", access_views.UserScopeView.as_view(), name="user-scope"),
    path("users/<int:pk>/access/", access_views.UserAccessView.as_view(), name="user-access"),
    path(
        "users/<int:pk>/overrides/", access_views.UserOverridesView.as_view(), name="user-overrides"
    ),
    path(
        "users/<int:pk>/reset-overrides/",
        access_views.UserResetOverridesView.as_view(),
        name="user-reset-overrides",
    ),
    path(
        "users/<int:pk>/copy-access/",
        access_views.UserCopyAccessView.as_view(),
        name="user-copy-access",
    ),
    path(
        "users/<int:pk>/deactivate/",
        access_views.UserDeactivateView.as_view(),
        name="user-deactivate",
    ),
    path("users/<int:pk>/history/", access_views.UserHistoryView.as_view(), name="user-history"),
    path(
        "overrides/pending/", access_views.PendingOverridesView.as_view(), name="overrides-pending"
    ),
    path(
        "overrides/<int:pk>/confirm/",
        access_views.OverrideConfirmView.as_view(),
        name="override-confirm",
    ),
    path(
        "overrides/<int:pk>/revoke/",
        access_views.OverrideRevokeView.as_view(),
        name="override-revoke",
    ),
    path("access-review/", access_views.AccessReviewView.as_view(), name="access-review"),
    path("audit/", audit_views.AuditLogView.as_view(), name="audit-log"),
]
