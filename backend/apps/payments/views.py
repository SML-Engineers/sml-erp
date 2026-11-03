"""Supplier payments API (spec 4.4 Cashier, 4.6). Rules live in services.py."""

from datetime import date

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import exports
from apps.core.permissions import AreaAccess
from apps.masters import banking
from apps.masters.models import CompanyAccount
from apps.vouchers import services as vouchers

from . import cancellations, certificate, services
from .models import PaymentCancellation, SupplierPayment
from .services import PaymentError


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _cancellation(p: SupplierPayment, user) -> dict | None:
    """The latest cancellation request of the payment, and what the user may do (P2-11)."""
    latest = p.cancellations.select_related("requested_by", "decided_by").first()
    if latest is None:
        return None
    return {
        "id": latest.pk,
        "status": latest.status,
        "reason": latest.reason,
        "requested_by": latest.requested_by.full_name,
        "requested_at": latest.requested_at,
        "decided_by": latest.decided_by.full_name if latest.decided_by_id else None,
        "decided_at": latest.decided_at,
        "reversal_entry": latest.reversal_entry.number if latest.reversal_entry_id else None,
        "can_decide": user is not None and cancellations.can_decide(user, latest),
    }


def payment_row(p: SupplierPayment, user=None) -> dict:
    return {
        "id": p.pk,
        "number": p.number,
        "voucher": {"id": p.voucher_id, "number": p.voucher.number},
        "payee": p.voucher.payee.name if p.voucher.payee else "",
        "account": {"id": p.account_id, "code": p.account.code, "name": p.account.name},
        "method": p.method,
        "reference": p.reference,
        "cheque_date": p.cheque_date,
        "payment_date": p.payment_date,
        "amount": f"{p.amount:.2f}",
        "journal_entry": p.journal_entry.number,
        # P2-11: what left the account, in its currency, and the rate; and cancelling.
        "currency": p.currency.code,
        "paid_amount": f"{p.paid_amount:.2f}",
        # P2-12: the withholding tax kept and its certificate.
        "wht_amount": f"{p.wht_amount:.2f}",
        "wht_certificate": p.wht_certificate,
        "exchange_rate": f"{p.exchange_rate.normalize():f}",
        "cancelled": p.cancelled,
        "cancellation": _cancellation(p, user),
        "can_cancel": user is not None
        and not p.cancelled
        and cancellations.can_request(user)
        and cancellations.pending(p) is None,
        "notes": p.notes,
        "created_by": p.created_by.full_name,
        "created_at": p.created_at,
    }


PAYMENT_COLUMNS = [
    exports.Column("number", "Payment", width=1.2),
    exports.Column("payment_date", "Date", "date"),
    exports.Column("voucher", "Voucher", width=1.3),
    exports.Column("payee", "Payee", width=2),
    exports.Column("account", "Paid from", width=1),
    exports.Column("method", "Method", width=1),
    exports.Column("reference", "Reference", width=1.2),
    exports.Column("entry", "Journal entry", width=1.1),
    exports.Column("amount", "Amount (LKR)", "money"),
]


class _Payments(APIView):
    permission_classes = [AreaAccess]
    access_area = "payments"
    access_write_level = "enter"


class ToPayView(_Payments):
    """The Cashier's list: Director-approved vouchers with what is left to pay."""

    def get(self, request):
        rows = []
        vouchers = services.to_pay(request.user)
        if request.query_params.get("division"):
            vouchers = vouchers.filter(division__code=request.query_params["division"].upper())
        for v in vouchers:
            paid = services.paid_on(v)
            suggested = services.suggested_account(v)
            currency, foreign_total = services.foreign_basis(v)
            rows.append(
                {
                    "id": v.pk,
                    "number": v.number,
                    "status": v.status,
                    "voucher_type": {"code": v.voucher_type.code, "name": v.voucher_type.name},
                    "division": v.division.code,
                    "payee": None if v.payee is None else {"id": v.payee_id, "name": v.payee.name},
                    "transfer_to": None if v.transfer_to is None else v.transfer_to.code,
                    "voucher_date": v.voucher_date,
                    "total_amount": f"{v.total_amount:.2f}",
                    "paid": f"{paid:.2f}",
                    "remaining": f"{v.total_amount - paid:.2f}",
                    # P2-12: the WHT to keep, and what is left to pay the payee after it.
                    "wht_total": f"{v.wht_total:.2f}",
                    "to_receive": f"{services.to_receive(v):.2f}",
                    "methods": services.methods_for(v),
                    "suggested_account": suggested.pk if suggested else None,
                    # P2-11: it may also be paid in this currency, from an account in it.
                    "foreign": None
                    if currency is None
                    else {
                        "currency": currency.code,
                        "total": f"{foreign_total:.2f}",
                        "left": f"{services.foreign_left(v, foreign_total):.2f}",
                    },
                }
            )
        return Response(rows)


class AccountsView(_Payments):
    """Accounts that can be paid from, with the next unused cheque of each."""

    def get(self, request):
        rows = []
        for a in CompanyAccount.objects.filter(is_active=True).select_related("currency"):
            upcoming = banking.next_cheque(a) if a.kind == CompanyAccount.Kind.CURRENT else None
            rows.append(
                {
                    "id": a.pk,
                    "code": a.code,
                    "name": a.name,
                    "kind": a.kind,
                    "currency": a.currency.code,
                    "has_ledger": a.ledger_account_id is not None,
                    "next_cheque": banking.format_cheque(*upcoming) if upcoming else None,
                }
            )
        return Response(rows)


class PaymentInput(serializers.Serializer):
    voucher = serializers.IntegerField()
    account = serializers.IntegerField()
    method = serializers.ChoiceField(choices=SupplierPayment.Method.choices)
    amount = serializers.CharField(max_length=30)
    payment_date = serializers.DateField(required=False)
    reference = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    cheque_number = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    cheque_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class PaymentListView(_Payments):
    def get(self, request):
        rows = services.visible(request.user).select_related(
            "voucher", "voucher__payee", "account", "journal_entry", "created_by"
        )
        params = request.query_params
        if params.get("voucher"):
            rows = rows.filter(voucher_id=params["voucher"])
        if params.get("from"):
            rows = rows.filter(payment_date__gte=params["from"])
        if params.get("to"):
            rows = rows.filter(payment_date__lte=params["to"])
        if params.get("division"):
            rows = rows.filter(voucher__division__code=params["division"].upper())
        if params.get("method"):
            rows = rows.filter(method=params["method"])
        if params.get("account"):
            rows = rows.filter(account_id=params["account"])
        fmt = (params.get("export") or "").lower()
        if fmt in exports.FORMATS:
            period = f"{params.get('from') or 'start'} to {params.get('to') or 'today'}"
            return exports.response(
                fmt,
                title="Payments made",
                subtitle=f"Supplier payments, {period}",
                columns=PAYMENT_COLUMNS,
                rows=[
                    {
                        "number": p.number,
                        "payment_date": p.payment_date,
                        "voucher": p.voucher.number,
                        "payee": p.voucher.payee.name if p.voucher.payee else "",
                        "account": p.account.code,
                        "method": p.get_method_display(),
                        "reference": p.reference,
                        "entry": p.journal_entry.number,
                        "amount": f"{p.amount:.2f}",
                    }
                    for p in rows[:5000]
                ],
                filename="payments",
                user=request.user,
            )
        return Response([payment_row(p, request.user) for p in rows[:1000]])

    def post(self, request):
        data = PaymentInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        voucher = get_object_or_404(vouchers.visible(request.user), pk=values["voucher"])
        account = get_object_or_404(CompanyAccount, pk=values["account"])
        payment_date: date = values.get("payment_date") or timezone.localdate()
        try:
            payment = services.record(
                request.user,
                voucher,
                account=account,
                method=values["method"],
                amount=values["amount"],
                payment_date=payment_date,
                reference=values["reference"],
                cheque_number=values.get("cheque_number"),
                cheque_date=values.get("cheque_date"),
                notes=values["notes"],
            )
        except PaymentError as error:
            return _error(error)
        payment = SupplierPayment.objects.select_related(
            "voucher", "voucher__payee", "account", "journal_entry", "created_by"
        ).get(pk=payment.pk)
        return Response(payment_row(payment, request.user), status=status.HTTP_201_CREATED)


def _payment(user, pk) -> SupplierPayment:
    rows = services.visible(user).select_related(
        "voucher", "voucher__payee", "account", "currency", "journal_entry", "created_by"
    )
    return get_object_or_404(rows, pk=pk)


class _Cancellations(_Payments):
    # The service decides: the Cashier or the Accountant asks, the Director decides.
    access_write_level = "view"


class CancelPaymentView(_Cancellations):
    """Ask to cancel a payment, with the reason."""

    def post(self, request, pk):
        payment = _payment(request.user, pk)
        try:
            cancellations.request(request.user, payment, str(request.data.get("reason", "")))
        except PaymentError as error:
            return _error(error)
        return Response(payment_row(_payment(request.user, pk), request.user))


class CancellationDecisionView(_Cancellations):
    decision = "approve"

    def post(self, request, pk):
        cancellation = get_object_or_404(PaymentCancellation, pk=pk)
        payment = _payment(request.user, cancellation.payment_id)
        try:
            if self.decision == "approve":
                cancellations.approve(
                    request.user, cancellation, str(request.data.get("comment", ""))
                )
            else:
                cancellations.reject(
                    request.user, cancellation, str(request.data.get("reason", ""))
                )
        except PaymentError as error:
            return _error(error)
        return Response(payment_row(_payment(request.user, payment.pk), request.user))


class CertificateView(_Payments):
    """The WHT certificate of a payment (P2-12), as a PDF."""

    def get(self, request, pk):
        payment = _payment(request.user, pk)
        if not payment.wht_certificate:
            return _error(
                PaymentError(f"No withholding tax was kept from payment {payment.number}.")
            )
        response = HttpResponse(certificate.render(payment), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{payment.wht_certificate}.pdf"'
        return response
