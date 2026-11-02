"""Taxes API (P0-20). Rules live in taxes.py. Everyone signed in may read the taxes and
calculate (document entry needs them); only the Accountant changes them."""

from datetime import date

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ReadForAllAreaWrite

from . import taxes
from .models import TaxCode, TaxCodeLine, TaxComponent, TaxRate
from .services import AccountingError


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _account(account):
    if account is None:
        return None
    return {"id": account.pk, "number": account.number, "name": account.name}


def _component(c: TaxComponent, today: date) -> dict:
    rates = [r for r in c.rates.all() if r.status == TaxRate.Status.CONFIRMED]
    current = next((r for r in rates if r.effective_from <= today), None)
    return {
        "id": c.pk,
        "code": c.code,
        "name": c.name,
        "printed_as": c.label,
        "kind": c.kind,
        "sales_account": _account(c.sales_account),
        "purchase_account": _account(c.purchase_account),
        "is_active": c.is_active,
        "in_use": c.first_used_at is not None,
        "current_rate": None if current is None else f"{current.rate.normalize():f}",
        "rates": [
            {
                "id": r.pk,
                "effective_from": r.effective_from,
                "rate": f"{r.rate.normalize():f}",
                "in_force": r.effective_from <= today,
            }
            for r in rates
        ],
    }


def _code(t: TaxCode) -> dict:
    return {
        "id": t.pk,
        "code": t.code,
        "name": t.name,
        "description": t.description,
        "use": t.use,
        "is_active": t.is_active,
        "in_use": t.first_used_at is not None,
        "components": [
            {
                "component": line.component_id,
                "code": line.component.code,
                "base": line.base,
                "portion_pct": f"{line.portion_pct:.2f}",
            }
            for line in t.lines.all()
        ],
    }


def overview() -> dict:
    today = timezone.localdate()
    components = TaxComponent.objects.select_related(
        "sales_account", "purchase_account"
    ).prefetch_related("rates")
    codes = TaxCode.objects.prefetch_related("lines__component")
    return {
        "components": [_component(c, today) for c in components],
        "codes": [_code(t) for t in codes],
    }


class _Taxes(APIView):
    permission_classes = [ReadForAllAreaWrite]
    access_area = "accounting"
    access_write_level = "manage"


class TaxOverviewView(_Taxes):
    def get(self, request):
        return Response(overview())


class ComponentInput(serializers.Serializer):
    code = serializers.CharField(max_length=40, required=False)
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    kind = serializers.CharField(max_length=10, required=False)
    sales_account = serializers.IntegerField(required=False, allow_null=True)
    purchase_account = serializers.IntegerField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


def _save_component(request, component):
    data = ComponentInput(data=request.data)
    data.is_valid(raise_exception=True)
    values = dict(data.validated_data)
    reason = values.pop("reason")
    try:
        taxes.save_component(request.user, component, values, reason)
    except AccountingError as error:
        return _error(error)
    return Response(overview(), status=status.HTTP_201_CREATED if component is None else 200)


class ComponentListView(_Taxes):
    def post(self, request):
        return _save_component(request, None)


class ComponentDetailView(_Taxes):
    def patch(self, request, pk):
        return _save_component(request, get_object_or_404(TaxComponent, pk=pk))


class RateInput(serializers.Serializer):
    effective_from = serializers.DateField()
    rate = serializers.CharField(max_length=20)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class RateListView(_Taxes):
    def post(self, request, pk):
        component = get_object_or_404(TaxComponent, pk=pk)
        data = RateInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            taxes.add_rate(
                request.user,
                component,
                effective_from=v["effective_from"],
                rate=v["rate"],
                reason=v["reason"],
            )
        except AccountingError as error:
            return _error(error)
        return Response(overview(), status=status.HTTP_201_CREATED)


class RateDetailView(_Taxes):
    def delete(self, request, pk, rate_pk):
        rate = get_object_or_404(TaxRate, pk=rate_pk, component_id=pk)
        try:
            taxes.remove_rate(request.user, rate, str(request.data.get("reason", "")))
        except AccountingError as error:
            return _error(error)
        return Response(overview())


class CodePart(serializers.Serializer):
    component = serializers.IntegerField()
    base = serializers.ChoiceField(choices=TaxCodeLine.Base.values, required=False)
    portion_pct = serializers.CharField(max_length=10, required=False, allow_blank=True)


class CodeInput(serializers.Serializer):
    code = serializers.CharField(max_length=40, required=False)
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    use = serializers.CharField(max_length=10, required=False)
    is_active = serializers.BooleanField(required=False)
    components = CodePart(many=True, required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


def _save_code(request, tax_code):
    data = CodeInput(data=request.data)
    data.is_valid(raise_exception=True)
    values = dict(data.validated_data)
    reason = values.pop("reason")
    if "components" in values:
        values["components"] = [dict(part) for part in values["components"]]
    try:
        taxes.save_code(request.user, tax_code, values, reason)
    except AccountingError as error:
        return _error(error)
    return Response(overview(), status=status.HTTP_201_CREATED if tax_code is None else 200)


class CodeListView(_Taxes):
    def post(self, request):
        return _save_code(request, None)


class CodeDetailView(_Taxes):
    def patch(self, request, pk):
        return _save_code(request, get_object_or_404(TaxCode, pk=pk))

    def delete(self, request, pk):
        tax_code = get_object_or_404(TaxCode, pk=pk)
        try:
            taxes.delete_code(request.user, tax_code, str(request.data.get("reason", "")))
        except AccountingError as error:
            return _error(error)
        return Response(overview())


class CalculateView(_Taxes):
    """The taxes of a tax code on an amount at a date: ?code=VAT-SSCL&amount=115750&date=…"""

    def get(self, request):
        params = request.query_params
        tax_code = TaxCode.objects.filter(code=(params.get("code") or "").upper()).first()
        if tax_code is None:
            return _error("Unknown tax code.")
        try:
            on_date = date.fromisoformat(params["date"]) if params.get("date") else None
        except ValueError:
            return _error("The date must look like 2026-10-31.")
        try:
            result = taxes.calculate(
                tax_code, params.get("amount", ""), on_date or timezone.localdate()
            )
        except AccountingError as error:
            return _error(error)
        return Response(
            {
                "code": tax_code.code,
                "net": f"{result.net:.2f}",
                "lines": [
                    {
                        "code": line.component.code,
                        "name": line.component.name,
                        "rate": f"{line.rate.normalize():f}",
                        "base": f"{line.base:.2f}",
                        "amount": f"{line.amount:.2f}",
                    }
                    for line in result.lines
                ],
                "tax": f"{result.tax:.2f}",
                "gross": f"{result.gross:.2f}",
            }
        )
