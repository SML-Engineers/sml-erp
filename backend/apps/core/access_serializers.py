from rest_framework import serializers

from .access import effective_access, sees_all_divisions
from .models import AccessOverride, Division, Role, User


class DivisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Division
        fields = ["id", "code", "name", "division_type", "is_active"]


class RolePermissionInput(serializers.Serializer):
    area = serializers.CharField(max_length=40)
    level = serializers.CharField(max_length=10)
    note = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "id",
            "code",
            "name",
            "description",
            "is_standard",
            "is_active",
            "permissions",
            "actions",
        ]

    def get_permissions(self, role):
        return [
            {"area": p.area, "level": p.level, "note": p.note}
            for p in role.permissions.order_by("area", "level")
        ]

    def get_actions(self, role):
        return sorted(role.actions.values_list("action", flat=True))


class RoleInput(serializers.Serializer):
    code = serializers.SlugField(max_length=50)
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    permissions = RolePermissionInput(many=True)
    actions = serializers.ListField(child=serializers.CharField(max_length=40), default=list)


class UserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    divisions = serializers.SlugRelatedField(many=True, read_only=True, slug_field="code")

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "is_active",
            "two_factor_required",
            "two_factor_enabled",
            "must_change_password",
            "all_divisions",
            "divisions",
            "roles",
            "last_login",
            "date_joined",
        ]

    def get_roles(self, user):
        return [
            {
                "code": a.role.code,
                "name": a.role.name,
                "assigned_at": a.assigned_at,
                "reason": a.reason,
                "conflict_warning": a.conflict_warning,
            }
            for a in user.role_assignments.select_related("role").order_by("role__name")
        ]


class UserCreateInput(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=150)


class UserUpdateInput(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, required=False)
    is_active = serializers.BooleanField(required=False)


class UserRolesInput(serializers.Serializer):
    roles = serializers.ListField(child=serializers.SlugField(max_length=50))
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class UserScopeInput(serializers.Serializer):
    all_divisions = serializers.BooleanField()
    divisions = serializers.ListField(
        child=serializers.CharField(max_length=2), required=False, default=list
    )


def access_payload(user: User) -> dict:
    data = effective_access(user).as_dict()
    data["divisions"] = (
        "all" if sees_all_divisions(user) else sorted(user.divisions.values_list("code", flat=True))
    )
    return data


class OverrideSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    created_by = serializers.SlugRelatedField(read_only=True, slug_field="email")
    confirmed_by = serializers.SlugRelatedField(read_only=True, slug_field="email")
    revoked_by = serializers.SlugRelatedField(read_only=True, slug_field="email")

    class Meta:
        model = AccessOverride
        fields = [
            "id",
            "user",
            "area",
            "level",
            "action",
            "effect",
            "reason",
            "ends_on",
            "is_sensitive",
            "status",
            "created_by",
            "created_at",
            "confirmed_by",
            "confirmed_at",
            "revoked_by",
            "revoked_at",
            "revoke_reason",
        ]


class OverrideInput(serializers.Serializer):
    effect = serializers.ChoiceField(choices=["grant", "remove"])
    area = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    level = serializers.CharField(max_length=10, required=False, allow_blank=True, default="")
    action = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    reason = serializers.CharField()
    ends_on = serializers.DateField(required=False, allow_null=True, default=None)


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class CopyAccessInput(serializers.Serializer):
    source_user = serializers.IntegerField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ReviewInput(serializers.Serializer):
    user = serializers.IntegerField()
    outcome = serializers.ChoiceField(choices=["confirmed", "changed"])
    note = serializers.CharField(required=False, allow_blank=True, default="")
    period = serializers.CharField(max_length=7, required=False, default="")
