from django.urls import path

from . import access_views, auth_views, views

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
    path("roles/", access_views.RoleListView.as_view(), name="role-list"),
    path("roles/<slug:code>/", access_views.RoleDetailView.as_view(), name="role-detail"),
    path("users/", access_views.UserListView.as_view(), name="user-list"),
    path("users/<int:pk>/", access_views.UserDetailView.as_view(), name="user-detail"),
    path("users/<int:pk>/roles/", access_views.UserRolesView.as_view(), name="user-roles"),
    path("users/<int:pk>/scope/", access_views.UserScopeView.as_view(), name="user-scope"),
]
