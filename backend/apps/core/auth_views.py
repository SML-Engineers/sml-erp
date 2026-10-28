"""Sign-in API under /api/v1/auth/. Thin views: the rules are in auth_services."""

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import auth_services as auth
from .access_serializers import access_payload
from .serializers import (
    CodeSerializer,
    LoginEventSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
)

INVALID_MESSAGE = "The email, password or code is not correct."
LOCKED_MESSAGE = (
    "Too many failed attempts. Sign-in is paused for 15 minutes. "
    "Contact the administrator if you need access sooner."
)


def _enforce_csrf(request):
    # DRF only checks CSRF for signed-in users; sign-in forms need it too.
    SessionAuthentication().enforce_csrf(request)


def _user_payload(user):
    return {
        "email": user.email,
        "full_name": user.full_name,
        "two_factor_enabled": user.two_factor_enabled,
        "two_factor_required": user.two_factor_required,
        "requirements": auth.setup_requirements(user),
        "access": access_payload(user),
    }


def _result_response(result):
    if result.status == "ok":
        return Response({"status": "ok", "user": _user_payload(result.user)})
    if result.status == "two_factor_required":
        return Response({"status": "two_factor_required"})
    if result.status == "locked":
        return Response({"status": "locked", "detail": LOCKED_MESSAGE}, status=429)
    return Response(
        {"status": "invalid", "detail": INVALID_MESSAGE}, status=status.HTTP_400_BAD_REQUEST
    )


@method_decorator(ensure_csrf_cookie, name="get")
class CsrfView(APIView):
    """Sets the CSRF cookie the React app sends back on every change."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "ok"})


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "login"

    def post(self, request):
        _enforce_csrf(request)
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = auth.sign_in(
            request, data.validated_data["email"], data.validated_data["password"]
        )
        return _result_response(result)


class LoginVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "login"

    def post(self, request):
        _enforce_csrf(request)
        data = CodeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return _result_response(auth.verify_second_factor(request, data.validated_data["code"]))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        auth.sign_out(request)
        return Response({"status": "signed_out"})


class MeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        if request.user.is_authenticated:
            return Response({"authenticated": True, "user": _user_payload(request.user)})
        return Response(
            {
                "authenticated": False,
                "two_factor_pending": auth.pending_two_factor_user(request) is not None,
            }
        )


class TwoFactorSetupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            return Response(auth.start_two_factor_setup(request.user))
        except auth.TwoFactorError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class TwoFactorConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = CodeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            codes = auth.confirm_two_factor(request, request.user, data.validated_data["code"])
        except auth.TwoFactorError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"recovery_codes": codes})


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = PasswordChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            auth.change_password(
                request,
                request.user,
                data.validated_data["current_password"],
                data.validated_data["new_password"],
            )
        except auth.PasswordChangeError as error:
            return Response({"detail": error.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": "ok", "user": _user_payload(request.user)})


class LoginHistoryView(APIView):
    """The signed-in user's own recent sign-in history (default permission applies)."""

    def get(self, request):
        events = request.user.login_events.all()[:50]
        return Response(LoginEventSerializer(events, many=True).data)
