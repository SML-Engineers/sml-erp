"""Users, roles and divisions API (P0-04). Thin views: the rules are in apps.core.access."""

import secrets

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import access, access_admin
from .access_defaults import ACTIONS, AREAS, LEVELS
from .access_serializers import (
    CopyAccessInput,
    DivisionSerializer,
    OverrideInput,
    OverrideSerializer,
    ReasonInput,
    ReviewInput,
    RoleInput,
    RoleSerializer,
    UserCreateInput,
    UserRolesInput,
    UserScopeInput,
    UserSerializer,
    UserUpdateInput,
)
from .audit import audit_context
from .models import AccessOverride, Division, Role, User
from .permissions import AreaAccess
from .serializers import LoginEventSerializer


def _error(error: access.AccessError, code=status.HTTP_400_BAD_REQUEST):
    return Response({"detail": str(error), "warnings": error.warnings}, status=code)


class CatalogView(APIView):
    """Areas, access levels and special actions, for building access screens."""

    def get(self, request):
        return Response(
            {
                "areas": [{"code": k, "label": v} for k, v in AREAS.items()],
                "levels": [{"code": k, "label": v} for k, v in LEVELS.items()],
                "actions": [{"code": k, "label": v} for k, v in ACTIONS.items()],
            }
        )


class DivisionListView(APIView):
    """The divisions the user may work in (used by every division picker).

    Pickers on new documents show active divisions only; list and report filters pass
    ?include_inactive=1 so older records of a deactivated division can still be found.
    """

    def get(self, request):
        divisions = access.division_scope(request.user)
        if request.query_params.get("include_inactive") not in ("1", "true"):
            divisions = divisions.filter(is_active=True)
        return Response(DivisionSerializer(divisions, many=True).data)


class DivisionDetailView(APIView):
    def get(self, request, code):
        division = get_object_or_404(access.division_scope(request.user), code=code.upper())
        return Response(DivisionSerializer(division).data)


class RoleListView(APIView):
    permission_classes = [AreaAccess]
    access_area = "users"
    access_write_level = "manage"

    def get(self, request):
        roles = Role.objects.prefetch_related("permissions", "actions")
        return Response(RoleSerializer(roles, many=True).data)

    def post(self, request):
        data = RoleInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                role = access.save_custom_role(None, **data.validated_data)
        except access.AccessError as error:
            return _error(error)
        except IntegrityError:
            return Response(
                {"detail": "A role with this code or name already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    permission_classes = [AreaAccess]
    access_area = "users"
    access_write_level = "manage"

    def get(self, request, code):
        return Response(RoleSerializer(get_object_or_404(Role, code=code)).data)

    def put(self, request, code):
        role = get_object_or_404(Role, code=code)
        data = RoleInput(data={**request.data, "code": code})
        data.is_valid(raise_exception=True)
        try:
            role = access.save_custom_role(role, **data.validated_data)
        except access.AccessError as error:
            return _error(error, status.HTTP_403_FORBIDDEN if role.is_standard else 400)
        return Response(RoleSerializer(role).data)


class UserListView(APIView):
    permission_classes = [AreaAccess]
    access_area = "users"
    access_write_level = "manage"

    def get(self, request):
        users = User.objects.prefetch_related("divisions", "role_assignments__role").order_by(
            "full_name"
        )
        return Response(UserSerializer(users, many=True).data)

    def post(self, request):
        data = UserCreateInput(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {"detail": "A user with this email already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        temporary_password = secrets.token_urlsafe(12)
        with audit_context("user_created"):
            user = User.objects.create_user(
                email,
                data.validated_data["full_name"],
                temporary_password,
                must_change_password=True,
            )
        body = UserSerializer(user).data
        body["temporary_password"] = temporary_password  # shown once, never stored in clear
        return Response(body, status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    permission_classes = [AreaAccess]
    access_area = "users"
    access_write_level = "manage"

    def get(self, request, pk):
        return Response(UserSerializer(get_object_or_404(User, pk=pk)).data)

    def patch(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        data = UserUpdateInput(data=request.data)
        data.is_valid(raise_exception=True)
        if user.pk == request.user.pk and data.validated_data.get("is_active") is False:
            return Response(
                {"detail": "You cannot deactivate your own account."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if data.validated_data.get("is_active") is False:
            access_admin.deactivate_user(request.user, user, "Deactivated by administrator")
            data.validated_data.pop("is_active")
        for field_name, value in data.validated_data.items():
            setattr(user, field_name, value)
        if data.validated_data:
            event = "user_reactivated" if data.validated_data.get("is_active") else "user_updated"
            with audit_context(event):
                user.save(update_fields=list(data.validated_data))
        user.refresh_from_db()
        return Response(UserSerializer(user).data)


class UserRolesView(APIView):
    permission_classes = [AreaAccess]
    access_area = "users"
    access_write_level = "manage"

    def put(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        data = UserRolesInput(data=request.data)
        data.is_valid(raise_exception=True)
        codes = data.validated_data["roles"]
        roles = list(Role.objects.filter(code__in=codes))
        if len(roles) != len(set(codes)):
            return Response({"detail": "Unknown role."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            warnings = access.set_user_roles(
                request.user, user, roles, data.validated_data["reason"]
            )
        except access.AccessError as error:
            self_change = user.pk == request.user.pk
            return _error(error, status.HTTP_403_FORBIDDEN if self_change else 400)
        user.refresh_from_db()
        return Response({"user": UserSerializer(user).data, "warnings": warnings})


class UserScopeView(APIView):
    permission_classes = [AreaAccess]
    access_area = "users"
    access_write_level = "manage"

    def put(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        data = UserScopeInput(data=request.data)
        data.is_valid(raise_exception=True)
        codes = [c.upper() for c in data.validated_data["divisions"]]
        divisions = list(Division.objects.filter(code__in=codes))
        if len(divisions) != len(set(codes)):
            return Response({"detail": "Unknown division."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            access.set_user_scope(
                request.user, user, data.validated_data["all_divisions"], divisions
            )
        except access.AccessError as error:
            return _error(error, status.HTTP_403_FORBIDDEN)
        user.refresh_from_db()
        return Response(UserSerializer(user).data)


# --- P0-04b: overrides, account lifecycle, history, access review ------------------------


class _UsersArea(APIView):
    permission_classes = [AreaAccess]
    access_area = "users"
    access_write_level = "manage"


class UserAccessView(_UsersArea):
    """The User access grid: role defaults, overrides and the result, area by area."""

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return Response({"user": UserSerializer(user).data, **access_admin.access_grid(user)})


class UserOverridesView(_UsersArea):
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return Response(OverrideSerializer(user.access_overrides.all(), many=True).data)

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        data = OverrideInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            override = access_admin.create_override(request.user, user, **data.validated_data)
        except access.AccessError as error:
            return _error(error, 403 if user.pk == request.user.pk else 400)
        return Response(OverrideSerializer(override).data, status=status.HTTP_201_CREATED)


class PendingOverridesView(_UsersArea):
    """Sensitive grants waiting for the Director."""

    def get(self, request):
        waiting = [
            o
            for o in AccessOverride.objects.filter(
                is_sensitive=True, confirmed_at__isnull=True, revoked_at__isnull=True
            ).select_related("user", "created_by")
            if o.status == "pending"
        ]
        return Response(OverrideSerializer(waiting, many=True).data)


class OverrideConfirmView(_UsersArea):
    # Viewing users is enough to reach this; the service requires the Director's action.
    access_write_level = "view"

    def post(self, request, pk):
        override = get_object_or_404(AccessOverride, pk=pk)
        try:
            access_admin.confirm_override(request.user, override)
        except access.AccessError as error:
            return _error(error, status.HTTP_403_FORBIDDEN)
        return Response(OverrideSerializer(override).data)


class OverrideRevokeView(_UsersArea):
    def post(self, request, pk):
        override = get_object_or_404(AccessOverride, pk=pk)
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            access_admin.revoke_override(request.user, override, data.validated_data["reason"])
        except access.AccessError as error:
            return _error(error, status.HTTP_403_FORBIDDEN)
        return Response(OverrideSerializer(override).data)


class UserResetOverridesView(_UsersArea):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            count = access_admin.reset_to_role_defaults(
                request.user, user, data.validated_data["reason"]
            )
        except access.AccessError as error:
            return _error(error, status.HTTP_403_FORBIDDEN)
        return Response({"ended": count})


class UserCopyAccessView(_UsersArea):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        data = CopyAccessInput(data=request.data)
        data.is_valid(raise_exception=True)
        source = get_object_or_404(User, pk=data.validated_data["source_user"])
        try:
            warnings = access_admin.copy_access(
                request.user, user, source, data.validated_data["reason"]
            )
        except access.AccessError as error:
            return _error(error, 403 if user.pk == request.user.pk else 400)
        user.refresh_from_db()
        return Response({"user": UserSerializer(user).data, "warnings": warnings})


class UserDeactivateView(_UsersArea):
    """A leaver: account off, signed out everywhere, overrides ended."""

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            access_admin.deactivate_user(request.user, user, data.validated_data["reason"])
        except access.AccessError as error:
            return _error(error, status.HTTP_403_FORBIDDEN)
        user.refresh_from_db()
        return Response(UserSerializer(user).data)


class UserHistoryView(_UsersArea):
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return Response(
            {
                "roles": UserSerializer(user).data["roles"],
                "overrides": OverrideSerializer(user.access_overrides.all(), many=True).data,
                "reviews": [
                    {
                        "period": r.period,
                        "outcome": r.outcome,
                        "reviewed_by": r.reviewed_by.email,
                        "reviewed_at": r.reviewed_at,
                        "note": r.note,
                    }
                    for r in user.access_reviews.select_related("reviewed_by").order_by("-period")
                ],
                "sign_ins": LoginEventSerializer(user.login_events.all()[:50], many=True).data,
            }
        )


class AccessReviewView(_UsersArea):
    # Viewing users is enough to see the review; recording it needs the Director's action.
    access_write_level = "view"

    def get(self, request):
        period = request.query_params.get("period") or access_admin.current_period()
        return Response({"period": period, "rows": access_admin.review_rows(period)})

    def post(self, request):
        data = ReviewInput(data=request.data)
        data.is_valid(raise_exception=True)
        user = get_object_or_404(User, pk=data.validated_data["user"])
        period = data.validated_data["period"] or access_admin.current_period()
        try:
            access_admin.record_review(
                request.user,
                user,
                period,
                data.validated_data["outcome"],
                data.validated_data["note"],
            )
        except access.AccessError as error:
            return _error(error, status.HTTP_403_FORBIDDEN)
        return Response({"period": period, "rows": access_admin.review_rows(period)})
