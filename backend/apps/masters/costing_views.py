"""Costing rates API (P15-02). Rules live in costing_rates.py.

Reading: anyone with Accounting or Sales view. Changing: the Accountant (Accounting: Manage).
"""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Division
from apps.core.permissions import AreaAccess

from . import costing_rates
from .models import CostingRate, Material, MaterialRate
from .services import MastersError


class CostingAccess(AreaAccess):
    """Accounting area, Manage to change; reading is also open to Sales (quotation costing)."""

    message = "You do not have access to costing rates."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS and super(AreaAccess, self).has_permission(request, view):
            if costing_rates.can_view(request.user):
                return True
        return super().has_permission(request, view)


class _Costing(APIView):
    permission_classes = [CostingAccess]
    access_area = "accounting"
    access_write_level = "manage"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _reason(request) -> str:
    return str(request.data.get("reason", "")) if hasattr(request.data, "get") else ""


class MaterialRateSerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(read_only=True, slug_field="email")
    in_force = serializers.SerializerMethodField()

    class Meta:
        model = MaterialRate
        fields = ["id", "effective_from", "rate", "reason", "created_by", "created_at", "in_force"]

    def get_in_force(self, rate) -> bool:
        return rate.effective_from <= timezone.localdate()


class MaterialSerializer(serializers.ModelSerializer):
    current_rate = serializers.SerializerMethodField()
    in_use = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = [
            "id",
            "code",
            "name",
            "kind",
            "form",
            "grade",
            "density",
            "notes",
            "is_active",
            "current_rate",
            "in_use",
        ]

    def get_current_rate(self, material):
        rate = costing_rates.material_rate_on(material, timezone.localdate())
        return None if rate is None else str(rate)

    def get_in_use(self, material) -> bool:
        return material.first_used_at is not None


class CostingRateSerializer(serializers.ModelSerializer):
    division = serializers.SlugRelatedField(read_only=True, slug_field="code")
    created_by = serializers.SlugRelatedField(read_only=True, slug_field="email")
    in_force = serializers.SerializerMethodField()
    current = serializers.SerializerMethodField()

    class Meta:
        model = CostingRate
        fields = [
            "id",
            "division",
            "effective_from",
            "overhead_pct",
            "margin_pct",
            "setup_rate",
            "reason",
            "created_by",
            "created_at",
            "in_force",
            "current",
        ]

    def get_in_force(self, rate) -> bool:
        return rate.effective_from <= timezone.localdate()

    def get_current(self, rate) -> bool:
        """The rates in force today for this division."""
        current = costing_rates.costing_rate_on(rate.division, timezone.localdate())
        return current is not None and current.pk == rate.pk


class MaterialInput(serializers.Serializer):
    code = serializers.CharField(max_length=30, required=False, allow_blank=True)
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    kind = serializers.CharField(max_length=20, required=False)
    form = serializers.CharField(max_length=20, required=False)
    grade = serializers.CharField(max_length=50, required=False, allow_blank=True)
    density = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class RateInput(serializers.Serializer):
    effective_from = serializers.DateField()
    # Received as text so the amount is exact (rule 1).
    rate = serializers.CharField(max_length=30)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class CostingRateInput(serializers.Serializer):
    division = serializers.CharField(max_length=2)
    effective_from = serializers.DateField()
    overhead_pct = serializers.CharField(max_length=20)
    margin_pct = serializers.CharField(max_length=20)
    setup_rate = serializers.CharField(max_length=30)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class MaterialListView(_Costing):
    def get(self, request):
        rows = Material.objects.prefetch_related("rates")
        if request.query_params.get("include_inactive") not in ("1", "true"):
            rows = rows.filter(is_active=True)
        if request.query_params.get("kind"):
            rows = rows.filter(kind=request.query_params["kind"])
        return Response(MaterialSerializer(rows, many=True).data)

    def post(self, request):
        data = MaterialInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("reason")
        values.pop("is_active", None)
        try:
            material = costing_rates.create_material(request.user, values)
        except MastersError as error:
            return _error(error)
        return Response(MaterialSerializer(material).data, status=status.HTTP_201_CREATED)


class MaterialDetailView(_Costing):
    def patch(self, request, pk):
        material = get_object_or_404(Material, pk=pk)
        data = MaterialInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        values.pop("code", None)  # a material's code never changes
        try:
            material = costing_rates.update_material(request.user, material, values, reason)
        except MastersError as error:
            return _error(error)
        return Response(MaterialSerializer(material).data)


class MaterialRatesView(_Costing):
    def get(self, request, pk):
        material = get_object_or_404(Material, pk=pk)
        return Response(MaterialRateSerializer(material.rates.all(), many=True).data)

    def post(self, request, pk):
        material = get_object_or_404(Material, pk=pk)
        data = RateInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            rate = costing_rates.add_material_rate(request.user, material, **data.validated_data)
        except MastersError as error:
            return _error(error)
        return Response(MaterialRateSerializer(rate).data, status=status.HTTP_201_CREATED)


class MaterialRateDetailView(_Costing):
    def delete(self, request, pk, rate_pk):
        rate = get_object_or_404(MaterialRate, pk=rate_pk, material_id=pk)
        try:
            costing_rates.remove_material_rate(request.user, rate, _reason(request))
        except MastersError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CostingRateListView(_Costing):
    def get(self, request):
        rows = CostingRate.objects.select_related("division", "created_by")
        if request.query_params.get("division"):
            rows = rows.filter(division__code=request.query_params["division"].upper())
        return Response(CostingRateSerializer(rows, many=True).data)

    def post(self, request):
        data = CostingRateInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        division = Division.objects.filter(code=values.pop("division").upper()).first()
        if division is None:
            return _error("Choose a division.")
        try:
            rate = costing_rates.add_costing_rate(request.user, division, **values)
        except MastersError as error:
            return _error(error)
        return Response(CostingRateSerializer(rate).data, status=status.HTTP_201_CREATED)


class CostingRateDetailView(_Costing):
    def delete(self, request, pk):
        rate = get_object_or_404(CostingRate, pk=pk)
        try:
            costing_rates.remove_costing_rate(request.user, rate, _reason(request))
        except MastersError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)
