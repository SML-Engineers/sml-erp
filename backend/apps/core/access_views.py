"""Users, roles and divisions API (P0-04). Thin views: the rules are in apps.core.access."""

import secrets

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import access
from .access_defaults import ACTIONS, AREAS, LEVELS
from .access_serializers import (
    DivisionSerializer,
    RoleInput,
    RoleSerializer,
    UserCreateInput,
    UserRolesInput,
    UserScopeInput,
    UserSerializer,
    UserUpdateInput,
)
from .models import Division, Role, User
from .permissions import AreaAccess


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
    """The divisions the user may work in (used by every division picker)."""

    def get(self, request):
        divisions = access.division_scope(request.user).filter(is_active=True)
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
        user = User.objects.create_user(
            email, data.validated_data["full_name"], temporary_password, must_change_password=True
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
        for field_name, value in data.validated_data.items():
            setattr(user, field_name, value)
        user.save(update_fields=list(data.validated_data) or None)
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
