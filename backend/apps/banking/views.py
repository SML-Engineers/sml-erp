"""Cheque register and deposits API (P2-14). Rules live in services.py."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess
from apps.masters.models import CompanyAccount

from . import services
from .models import Deposit
from .services import BankingError


class _Banking(APIView):
    permission_classes = [AreaAccess]
    access_area = "banking"
    access_also_area = "payments"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _issued(leaf) -> dict:
    payment = getattr(leaf, "payment", None)
    clearance = getattr(leaf, "clearance", None)
    return {
        "id": leaf.pk,
        "number": f"{leaf.number:0{leaf.book.digits}d}",
        "account": {"id": leaf.account_id, "code": leaf.account.code},
        "status": services.issued_status(leaf),
        "reason": leaf.reason,
        "used_at": leaf.used_at,
        "cleared_on": clearance.cleared_on if clearance else None,
        "payment": None
        if payment is None
        else {
            "id": payment.pk,
            "number": payment.number,
            "date": payment.payment_date,
            "cheque_date": payment.cheque_date,
            "amount": f"{payment.paid_amount:.2f}",
            "payee": payment.voucher.payee.name if payment.voucher.payee else "",
            "voucher": {"id": payment.voucher_id, "number": payment.voucher.number},
        },
    }


def _received(r) -> dict:
    line = getattr(r, "deposit_line", None)
    clearance = getattr(line, "clearance", None) if line else None
    return {
        "id": r.pk,
        "number": r.number,
        "customer": {"id": r.customer_id, "name": r.customer.name},
        "reference": r.reference,
        "cheque_bank": r.cheque_bank,
        "cheque_date": r.cheque_date,
        "receipt_date": r.receipt_date,
        "currency": r.currency.code,
        "amount": f"{r.amount:.2f}",
        "amount_lkr": f"{r.amount_lkr:.2f}",
        "status": services.received_status(r),
        "deposit": None
        if line is None
        else {
            "id": line.deposit_id,
            "number": line.deposit.number,
            "date": line.deposit.deposit_date,
        },
        "cleared_on": clearance.cleared_on if clearance else None,
        "returned_on": r.returned_on,
        "return_reason": r.return_reason,
    }


class IssuedView(_Banking):
    def get(self, request):
        rows = services.issued(request.user).order_by("-used_at", "-id")
        wanted = request.query_params.get("status")
        found = [_issued(leaf) for leaf in rows[:3000]]
        if wanted:
            found = [row for row in found if row["status"] == wanted]
        return Response(found)


class ReceivedView(_Banking):
    def get(self, request):
        rows = services.received(request.user).order_by("-receipt_date", "-number")
        wanted = request.query_params.get("status")
        found = [_received(r) for r in rows[:3000]]
        if wanted:
            found = [row for row in found if row["status"] == wanted]
        return Response(found)


class DayIn(serializers.Serializer):
    on = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ClearIssuedView(_Banking):
    def post(self, request, pk):
        leaf = get_object_or_404(services.issued(request.user), pk=pk)
        body = DayIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            services.clear_issued(request.user, leaf, body.validated_data["on"])
        except BankingError as error:
            return _error(error)
        return Response(_issued(services.issued(request.user).get(pk=pk)))


class ClearReceivedView(_Banking):
    def post(self, request, pk):
        receipt = get_object_or_404(services.received(request.user), pk=pk)
        body = DayIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            services.clear_received(request.user, receipt, body.validated_data["on"])
        except BankingError as error:
            return _error(error)
        return Response(_received(services.received(request.user).get(pk=pk)))


class ReturnReceivedView(_Banking):
    def post(self, request, pk):
        receipt = get_object_or_404(services.received(request.user), pk=pk)
        body = DayIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            services.return_cheque(
                request.user,
                receipt,
                returned_on=body.validated_data["on"],
                reason=body.validated_data["reason"],
            )
        except BankingError as error:
            return _error(error)
        return Response(_received(services.received(request.user).get(pk=pk)))


def _deposit(d: Deposit) -> dict:
    return {
        "id": d.pk,
        "number": d.number,
        "account": {"id": d.account_id, "code": d.account.code, "name": d.account.name},
        "deposit_date": d.deposit_date,
        "slip_no": d.slip_no,
        "total": f"{d.total:.2f}",
        "journal_entry": d.journal_entry.number,
        "created_by": d.created_by.full_name,
        "cheques": [
            _received(line.receipt)
            for line in d.lines.select_related(
                "receipt__customer", "receipt__currency", "receipt__deposit_line__deposit"
            )
        ],
    }


class DepositIn(serializers.Serializer):
    account = serializers.IntegerField()
    deposit_date = serializers.DateField()
    slip_no = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    receipts = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class DepositListView(_Banking):
    def get(self, request):
        return Response([_deposit(d) for d in services.deposits(request.user)[:500]])

    def post(self, request):
        body = DepositIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        receipts = list(services.received(request.user).filter(pk__in=data["receipts"]))
        if len(receipts) != len(set(data["receipts"])):
            return _error(BankingError("Some of the cheques chosen cannot be found."))
        try:
            made = services.deposit(
                request.user,
                account=CompanyAccount.objects.select_related("currency", "ledger_account")
                .filter(pk=data["account"])
                .first(),
                deposit_date=data["deposit_date"],
                receipts=receipts,
                slip_no=data["slip_no"],
            )
        except BankingError as error:
            return _error(error)
        return Response(_deposit(made), status=status.HTTP_201_CREATED)


class DepositDetailView(_Banking):
    def get(self, request, pk):
        return Response(_deposit(get_object_or_404(services.deposits(request.user), pk=pk)))
