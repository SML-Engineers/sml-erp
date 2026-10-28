"""Payment vouchers API (spec 4). Rules live in services.py."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ReadForAllAreaWrite
from apps.masters.services import is_in_use

from . import services
from .models import VoucherType
from .services import VoucherError


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _type(vt: VoucherType) -> dict:
    return {
        "id": vt.pk,
        "code": vt.code,
        "name": vt.name,
        "payment_method": vt.payment_method,
        "needs_payee": vt.needs_payee,
        "payee_category": vt.payee_category,
        "is_advance": vt.is_advance,
        "notes": vt.notes,
        "sort_order": vt.sort_order,
        "is_active": vt.is_active,
        "in_use": is_in_use(vt),
    }


class TypeInput(serializers.Serializer):
    code = serializers.CharField(max_length=20, required=False)
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    payment_method = serializers.CharField(max_length=30, required=False)
    needs_payee = serializers.BooleanField(required=False)
    payee_category = serializers.CharField(max_length=20, required=False, allow_blank=True)
    is_advance = serializers.BooleanField(required=False)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True)
    sort_order = serializers.IntegerField(required=False)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class _Types(APIView):
    """Everyone signed in may read the types (the voucher form lists them); only the
    Admin changes them."""

    permission_classes = [ReadForAllAreaWrite]
    access_area = "settings"
    access_write_level = "manage"


class TypeListView(_Types):
    def get(self, request):
        rows = VoucherType.objects.all()
        if request.query_params.get("include_inactive") not in ("1", "true"):
            rows = rows.filter(is_active=True)
        return Response([_type(vt) for vt in rows])

    def post(self, request):
        data = TypeInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("is_active", None)
        try:
            vt = services.create_type(
                request.user,
                code=values.pop("code", ""),
                name=values.pop("name", ""),
                payment_method=values.pop("payment_method", ""),
                **values,
            )
        except VoucherError as error:
            return _error(error)
        return Response(_type(vt), status=status.HTTP_201_CREATED)


class TypeDetailView(_Types):
    def patch(self, request, pk):
        vt = get_object_or_404(VoucherType, pk=pk)
        data = TypeInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            vt = services.update_type(request.user, vt, values, reason)
        except VoucherError as error:
            return _error(error)
        return Response(_type(vt))

    def delete(self, request, pk):
        vt = get_object_or_404(VoucherType, pk=pk)
        try:
            services.delete_type(request.user, vt, str(request.data.get("reason", "")))
        except VoucherError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)
