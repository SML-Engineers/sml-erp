"""Customer receipts API (P2-07). Rules live in receipts.py. Area: Supplier payments and
receipts (the Cashier enters, the Accountant and Director look); approving is checked by the
approval engine (the Accountant's role, never one's own receipt). Setting off an advance by
hand is the Accountant's (Accounting: Manage)."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.permissions import AreaAccess
from apps.masters.models import CompanyAccount, Customer

from . import advances, receipt, receipts
from .advance_views import _detail as advance_detail
from .models import CustomerAdvance, CustomerReceipt, TaxInvoice
from .services import SalesError


class _Receipts(APIView):
    permission_classes = [AreaAccess]
    access_area = "payments"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _get(user, pk) -> CustomerReceipt:
    rows = receipts.visible(user).select_related(
        "customer", "account", "currency", "created_by", "approved_by", "journal_entry"
    )
    return get_object_or_404(rows, pk=pk)


def _row(r: CustomerReceipt) -> dict:
    return {
        "id": r.id,
        "number": r.number,
        "receipt_date": r.receipt_date,
        "customer": {"id": r.customer_id, "code": r.customer.code, "name": r.customer.name},
        "method": r.method,
        "reference": r.reference,
        "cheque_date": r.cheque_date,
        "currency": r.currency.code,
        "amount": f"{r.amount:.2f}",
        "amount_lkr": f"{r.amount_lkr:.2f}",
        "status": r.status,
        "created_by": r.created_by.full_name,
    }


def _detail(r: CustomerReceipt, user) -> dict:
    body = _row(r)
    body |= {
        "account": None
        if r.account_id is None
        else {"id": r.account_id, "code": r.account.code, "name": r.account.name},
        "cheque_bank": r.cheque_bank,
        "exchange_rate": f"{r.exchange_rate.normalize():f}",
        "rate_date": r.rate_date,
        "notes": r.notes,
        "allocations": [
            {
                "invoice": {
                    "id": a.invoice_id,
                    "number": a.invoice.number,
                    "invoice_date": a.invoice.invoice_date,
                    "division": a.invoice.division.code,
                    "total_amount": f"{a.invoice.total_amount:.2f}",
                },
                "amount": f"{a.amount:.2f}",
            }
            for a in r.allocations.select_related("invoice__division").order_by("id")
        ],
        "journal_entry": None
        if r.journal_entry_id is None
        else {"id": r.journal_entry_id, "number": r.journal_entry.number},
        "approved_by": r.approved_by.full_name if r.approved_by_id else None,
        "approved_at": r.approved_at,
        "posted_at": r.posted_at,
        "can_approve": receipts.can_approve(user, r),
        "history": [
            {
                "action": row.action,
                "action_label": row.get_action_display(),
                "by": row.user.full_name,
                "at": row.acted_at,
                "reason": row.reason,
            }
            for row in approvals.history(receipts.DOC, r.pk)
        ],
    }
    return body


def open_invoice(invoice: TaxInvoice, figures: dict) -> dict:
    return {
        "id": invoice.pk,
        "number": invoice.number,
        "invoice_date": invoice.invoice_date,
        "due_date": invoice.due_date,
        "division": invoice.division.code,
        "customer_po": invoice.customer_po,
        "currency": invoice.currency.code,
        "total_amount": f"{figures['total']:.2f}",
        "open_amount": f"{figures['open']:.2f}",
    }


class AllocationInput(serializers.Serializer):
    invoice = serializers.IntegerField()
    amount = serializers.CharField(max_length=30)


class ReceiptInput(serializers.Serializer):
    customer = serializers.IntegerField()
    method = serializers.CharField(max_length=10)
    account = serializers.IntegerField(required=False, allow_null=True)
    amount = serializers.CharField(max_length=30)
    receipt_date = serializers.DateField()
    reference = serializers.CharField(max_length=50, required=False, allow_blank=True)
    cheque_date = serializers.DateField(required=False, allow_null=True)
    cheque_bank = serializers.CharField(max_length=100, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    allocations = AllocationInput(many=True)


class ReceiptListView(_Receipts):
    def get(self, request):
        rows = receipts.visible(request.user).select_related("customer", "currency", "created_by")
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("customer"):
            rows = rows.filter(customer_id=params["customer"])
        if params.get("waiting") == "me":
            waiting = approvals.waiting_for(request.user, receipts.DOC)
            rows = rows.filter(pk__in=[state.document_id for state in waiting])
        return Response([_row(r) for r in rows[:2000]])

    def post(self, request):
        data = ReceiptInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        wanted = [part["invoice"] for part in values["allocations"]]
        found = {i.pk: i for i in TaxInvoice.objects.filter(pk__in=wanted)}
        if len(found) != len(set(wanted)):
            return _error("One of the invoices does not exist.")
        account = None
        if values.get("account"):
            account = CompanyAccount.objects.filter(pk=values["account"]).first()
        try:
            made = receipts.record(
                request.user,
                customer=Customer.objects.filter(pk=values["customer"]).first(),
                method=values["method"],
                account=account,
                amount=values["amount"],
                receipt_date=values["receipt_date"],
                reference=values.get("reference", ""),
                cheque_date=values.get("cheque_date"),
                cheque_bank=values.get("cheque_bank", ""),
                notes=values.get("notes", ""),
                allocations=[
                    receipts.Allocation(found[part["invoice"]], part["amount"])
                    for part in values["allocations"]
                ],
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(made, request.user), status=status.HTTP_201_CREATED)


class ReceiptOptionsView(_Receipts):
    """What the Cashier chooses from: customers with open invoices (oldest first, with what is
    open on each, in its currency) and the accounts money is received into."""

    def get(self, request):
        by_customer: dict[int, dict] = {}
        for invoice, figures in receipts.open_invoices(request.user):
            customer = invoice.customer
            entry = by_customer.setdefault(
                customer.pk,
                {"id": customer.pk, "code": customer.code, "name": customer.name, "invoices": []},
            )
            entry["invoices"].append(open_invoice(invoice, figures))
        return Response(
            {
                "can_record": receipts.can_record(request.user),
                "customers": sorted(by_customer.values(), key=lambda c: c["name"]),
                "accounts": [
                    {
                        "id": a.id,
                        "code": a.code,
                        "name": a.name,
                        "kind": a.kind,
                        "currency": a.currency.code,
                    }
                    for a in CompanyAccount.objects.filter(
                        is_active=True, ledger_account__isnull=False
                    ).select_related("currency")
                ],
            }
        )


class ReceiptDetailView(_Receipts):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk), request.user))


class _Decision(_Receipts):
    # The approval engine decides who may act (the Accountant, never on their own receipt).
    access_write_level = "view"


class ReceiptApproveView(_Decision):
    def post(self, request, pk):
        made = _get(request.user, pk)
        try:
            made = receipts.approve(request.user, made, str(request.data.get("comment", "")))
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, made.pk), request.user))


class ReceiptRejectView(_Decision):
    def post(self, request, pk):
        made = _get(request.user, pk)
        try:
            made = receipts.reject(request.user, made, str(request.data.get("reason", "")))
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, made.pk), request.user))


class ReceiptPdfView(_Receipts):
    def get(self, request, pk):
        made = _get(request.user, pk)
        response = HttpResponse(receipt.render_receipt(made), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="Receipt {made.number}.pdf"'
        return response


class SetOffInput(serializers.Serializer):
    invoice = serializers.IntegerField()
    amount = serializers.CharField(max_length=30)


class AdvanceSetOffView(APIView):
    """The Accountant sets off an approved advance against an open invoice of the customer."""

    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "manage"

    def post(self, request, pk):
        advance = get_object_or_404(advances.visible(request.user), pk=pk)
        data = SetOffInput(data=request.data)
        data.is_valid(raise_exception=True)
        invoice = TaxInvoice.objects.filter(pk=data.validated_data["invoice"]).first()
        if invoice is None:
            return _error("That invoice does not exist.")
        try:
            receipts.set_off(request.user, advance, invoice, data.validated_data["amount"])
        except SalesError as error:
            return _error(error)
        return Response(advance_detail(CustomerAdvance.objects.get(pk=advance.pk), request.user))
