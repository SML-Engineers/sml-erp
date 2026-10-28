from django.urls import path

from . import auth_views, views

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
]
