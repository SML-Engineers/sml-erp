"""Quotation approval limits API (P0-12). Rules live in limits.py."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Division
from apps.core.permissions import AreaAccess

from . import limits
from .models import QuotationLimit


class LimitSerializer(serializers.ModelSerializer):
    division = serializers.SlugRelatedField(read_only=True, slug_field="code")
    created_by = serializers.SlugRelatedField(read_only=True, slug_field="email")
    decided_by = serializers.SlugRelatedField(read_only=True, slug_field="email")
    in_force = serializers.SerializerMethodField()

    class Meta:
        model = QuotationLimit
        fields = [
            "id",
            "division",
            "effective_from",
            "min_margin_pct",
            "director_above_lkr",
            "status",
            "reason",
            "created_by",
            "created_at",
            "decided_by",
            "decided_at",
            "decision_note",
            "in_force",
        ]

    def get_in_force(self, limit) -> bool:
        current = limits.in_force(limit.division, timezone.localdate())
        return current is not None and current.pk == limit.pk


class LimitInput(serializers.Serializer):
    division = serializers.CharField(max_length=2)
    effective_from = serializers.DateField()
    # Text, so the figures stay exact (rule 1).
    min_margin_pct = serializers.CharField(max_length=20)
    director_above_lkr = serializers.CharField(max_length=30, required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class NoteInput(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


def _error(error, code=status.HTTP_400_BAD_REQUEST):
    return Response({"detail": str(error)}, status=code)


class _Limits(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "manage"


class LimitListView(_Limits):
    def get(self, request):
        rows = QuotationLimit.objects.select_related("division", "created_by", "decided_by")
        return Response(LimitSerializer(rows, many=True).data)

    def post(self, request):
        data = LimitInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        division = Division.objects.filter(code=v["division"].strip().upper()).first()
        if division is None:
            return _error(f"Unknown division {v['division']}.")
        try:
            limit = limits.propose(
                user=request.user,
                division=division,
                effective_from=v["effective_from"],
                min_margin_pct=v["min_margin_pct"],
                director_above_lkr=v.get("director_above_lkr", ""),
                reason=v["reason"],
            )
        except limits.LimitError as error:
            return _error(error)
        return Response(LimitSerializer(limit).data, status=status.HTTP_201_CREATED)


class _Decision(_Limits):
    # Viewing settings is enough to reach this; the service requires the Director's action.
    access_write_level = "view"


class LimitConfirmView(_Decision):
    def post(self, request, pk):
        try:
            limit = limits.confirm(request.user, get_object_or_404(QuotationLimit, pk=pk))
        except limits.LimitError as error:
            return _error(error)
        return Response(LimitSerializer(limit).data)


class LimitRejectView(_Decision):
    def post(self, request, pk):
        data = NoteInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            limit = limits.reject(
                request.user, get_object_or_404(QuotationLimit, pk=pk), data.validated_data["note"]
            )
        except limits.LimitError as error:
            return _error(error)
        return Response(LimitSerializer(limit).data)


class LimitWithdrawView(_Limits):
    def post(self, request, pk):
        try:
            limit = limits.withdraw(request.user, get_object_or_404(QuotationLimit, pk=pk))
        except limits.LimitError as error:
            return _error(error)
        return Response(LimitSerializer(limit).data)
