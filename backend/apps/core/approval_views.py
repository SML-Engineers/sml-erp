"""Approval matrix settings API (P0-17). Rules live in approvals.py."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import approvals
from .approvals import ApprovalError
from .models import ApprovalRule, Division, Role
from .permissions import AreaAccess, IsFullyAuthenticated


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _rule(rule: ApprovalRule) -> dict:
    return {
        "id": rule.pk,
        "document_type": rule.document_type,
        "level": rule.level,
        "role": {"code": rule.role.code, "name": rule.role.name},
        "min_amount": None if rule.min_amount is None else f"{rule.min_amount:.2f}",
        "max_amount": None if rule.max_amount is None else f"{rule.max_amount:.2f}",
        "division": rule.division.code if rule.division else None,
        "subtype": rule.subtype,
        "is_active": rule.is_active,
        "created_at": rule.created_at,
    }


def _matrix() -> dict:
    return {
        "document_types": [
            {
                "code": code,
                "name": kind.name,
                "min_approvals": kind.min_approvals,
                "final_role": kind.final_role,
                "subtype_label": kind.subtype_label,
            }
            for code, kind in approvals.DOCUMENT_TYPES.items()
        ],
        "rules": [_rule(r) for r in ApprovalRule.objects.select_related("role", "division")],
        "roles": [{"code": r.code, "name": r.name} for r in Role.objects.filter(is_active=True)],
    }


class RuleInput(serializers.Serializer):
    document_type = serializers.CharField(max_length=30)
    level = serializers.IntegerField()
    role = serializers.CharField(max_length=50)
    min_amount = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    max_amount = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    division = serializers.CharField(
        max_length=2, required=False, allow_blank=True, allow_null=True
    )
    subtype = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    reason = serializers.CharField(required=False, allow_blank=True, default="")


def _division(code):
    code = (code or "").strip().upper()
    if not code:
        return None
    division = Division.objects.filter(code=code).first()
    if division is None:
        raise ApprovalError(f"Unknown division {code}.")
    return division


class _Matrix(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "manage"


class MatrixView(_Matrix):
    def get(self, request):
        return Response(_matrix())

    def post(self, request):
        data = RuleInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        role = Role.objects.filter(code=v["role"]).first()
        if role is None:
            return _error("Unknown role.")
        try:
            approvals.add_rule(
                request.user,
                document_type=v["document_type"],
                level=v["level"],
                role=role,
                min_amount=v.get("min_amount"),
                max_amount=v.get("max_amount"),
                division=_division(v.get("division")),
                subtype=v["subtype"],
                reason=v["reason"],
            )
        except ApprovalError as error:
            return _error(error)
        return Response(_matrix(), status=status.HTTP_201_CREATED)


class RuleSwitchOffView(_Matrix):
    def post(self, request, pk):
        rule = get_object_or_404(ApprovalRule, pk=pk)
        try:
            approvals.switch_off_rule(request.user, rule, str(request.data.get("reason", "")))
        except ApprovalError as error:
            return _error(error)
        return Response(_matrix())


class RoutePreviewView(_Matrix):
    """The route a document with these details would take: to check a matrix change."""

    def get(self, request):
        params = request.query_params
        try:
            route = approvals.route_for(
                params.get("document_type", ""),
                amount=params.get("amount") or None,
                division=_division(params.get("division")),
                subtype=params.get("subtype", ""),
            )
        except ApprovalError as error:
            return _error(error)
        return Response(route)


class ReminderView(_Matrix):
    """Reminders for documents waiting too long, per document type (P1-09)."""

    def get(self, request):
        return Response(approvals.reminder_settings())

    def put(self, request):
        try:
            rows = approvals.set_reminder(
                request.user,
                str(request.data.get("document_type", "")),
                enabled=request.data.get("enabled") in (True, "true", "1", 1),
                after_days=request.data.get("after_days"),
                reason=str(request.data.get("reason", "")),
            )
        except ApprovalError as error:
            return _error(error)
        return Response(rows)


class WaitingForMeView(APIView):
    """What waits for this person's approval, by kind of document (owner, 12 Nov 2026): the
    same queue each document's own page uses, counted for the dashboard."""

    permission_classes = [IsFullyAuthenticated]

    def get(self, request):
        counts: dict[str, int] = {}
        for state in approvals.waiting_for(request.user):
            counts[state.document_type] = counts.get(state.document_type, 0) + 1
        return Response(
            [
                {
                    "document_type": code,
                    "label": approvals.DOCUMENT_TYPES[code].name
                    if code in approvals.DOCUMENT_TYPES
                    else code,
                    "count": count,
                }
                for code, count in sorted(counts.items())
            ]
        )
