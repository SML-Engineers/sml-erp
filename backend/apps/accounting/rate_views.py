"""Tax rates control panel API (P16-20; owner's decision of 2 Nov 2026). Rules live in
taxes.py.

Settings → Tax rates: the rates of every tax charged on documents (VAT and the three SSCL
rates), in force and waiting. The Admin or the Accountant enters a change from a date; it takes
effect only when the Director confirms it. Reading needs Settings: View; the service checks
who may propose and confirm."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess

from . import taxes
from .models import TaxComponent, TaxRate
from .services import AccountingError


class _Rates(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "view"  # the service checks who may propose, confirm and withdraw


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _rate(r: TaxRate) -> dict:
    return {
        "id": r.pk,
        "effective_from": r.effective_from,
        "rate": f"{r.rate.normalize():f}",
        "status": r.status,
        "reason": r.reason,
        "created_by": r.created_by.full_name if r.created_by else "",
        "created_by_me": False,
        "decided_by": r.decided_by.full_name if r.decided_by else "",
        "decided_at": r.decided_at,
        "decision_note": r.decision_note,
    }


def overview(user) -> dict:
    today = timezone.localdate()
    rows = []
    for c in TaxComponent.objects.filter(kind=TaxComponent.Kind.CHARGED).prefetch_related(
        "rates__created_by", "rates__decided_by"
    ):
        rates = sorted(c.rates.all(), key=lambda r: (r.effective_from, r.pk), reverse=True)
        confirmed = [r for r in rates if r.status == TaxRate.Status.CONFIRMED]
        current = next((r for r in confirmed if r.effective_from <= today), None)
        coming = [r for r in confirmed if r.effective_from > today]
        rows.append(
            {
                "id": c.pk,
                "code": c.code,
                "name": c.name,
                "printed_as": c.label,
                "is_active": c.is_active,
                "current": None if current is None else _rate(current),
                "coming": [_rate(r) for r in sorted(coming, key=lambda r: r.effective_from)],
                "pending": [
                    _rate(r) | {"created_by_me": r.created_by_id == user.pk}
                    for r in rates
                    if r.status == TaxRate.Status.PENDING
                ],
                "history": [_rate(r) for r in rates],
            }
        )
    return {
        "taxes": rows,
        "can_propose": taxes.can_propose_rates(user),
        "can_confirm": taxes.can_confirm_rates(user),
    }


class ProposeInput(serializers.Serializer):
    component = serializers.IntegerField()
    effective_from = serializers.DateField()
    rate = serializers.CharField(max_length=20)  # text, so the figure stays exact (rule 1)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class RateListView(_Rates):
    def get(self, request):
        return Response(overview(request.user))

    def post(self, request):
        data = ProposeInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        component = TaxComponent.objects.filter(pk=v["component"]).first()
        if component is None:
            return _error("Choose the tax.")
        try:
            taxes.propose_rate(
                request.user,
                component,
                effective_from=v["effective_from"],
                rate=v["rate"],
                reason=v["reason"],
            )
        except AccountingError as error:
            return _error(error)
        return Response(overview(request.user), status=status.HTTP_201_CREATED)


class _Decision(_Rates):
    def _run(self, request, pk, action):
        rate = get_object_or_404(TaxRate, pk=pk)
        try:
            action(rate)
        except AccountingError as error:
            return _error(error)
        return Response(overview(request.user))


class RateConfirmView(_Decision):
    def post(self, request, pk):
        return self._run(request, pk, lambda r: taxes.confirm_rate(request.user, r))


class RateRejectView(_Decision):
    def post(self, request, pk):
        note = str(request.data.get("note", ""))
        return self._run(request, pk, lambda r: taxes.reject_rate(request.user, r, note))


class RateWithdrawView(_Decision):
    def post(self, request, pk):
        return self._run(request, pk, lambda r: taxes.withdraw_rate(request.user, r))
