"""Customer advances API (P15-09). Rules live in advances.py. Area: Supplier payments and
receipts (the Cashier enters, the Accountant and Director look); approving is checked by the
approval engine (the Accountant's role, and never one's own receipt)."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.access import division_scope
from apps.core.models import Division
from apps.core.permissions import AreaAccess
from apps.masters.models import CompanyAccount, Customer

from . import advances, receipt
from .models import CustomerAdvance, ProformaInvoice, Quotation
from .services import SalesError


class _Advances(APIView):
    permission_classes = [AreaAccess]
    access_area = "payments"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _get(user, pk) -> CustomerAdvance:
    return get_object_or_404(advances.visible(user), pk=pk)


def _row(a: CustomerAdvance) -> dict:
    return {
        "id": a.id,
        "number": a.number,
        "receipt_date": a.receipt_date,
        "customer": {"id": a.customer_id, "code": a.customer.code, "name": a.customer.name},
        "quotation": None
        if a.quotation_id is None
        else {"id": a.quotation_id, "label": a.quotation.label},
        "proforma": None
        if a.proforma_id is None
        else {"id": a.proforma_id, "number": a.proforma.number},
        "division": a.division.code,
        "currency": a.currency.code,
        "amount": str(a.amount),
        "amount_lkr": str(a.amount_lkr),
        "balance_lkr": str(advances.balance_lkr(a)),
        "method": a.method,
        "status": a.status,
        "created_by": a.created_by.full_name,
    }


def _detail(a: CustomerAdvance, user) -> dict:
    body = _row(a)
    body |= {
        "account": {"id": a.account_id, "code": a.account.code, "name": a.account.name},
        "reference": a.reference,
        "exchange_rate": str(a.exchange_rate),
        "rate_date": a.rate_date,
        "set_off_lkr": str(a.set_off_lkr),
        "notes": a.notes,
        "journal_entry": None
        if a.journal_entry_id is None
        else {"id": a.journal_entry_id, "number": a.journal_entry.number},
        "approved_at": a.approved_at,
        "can_approve": advances.can_approve(user, a),
        "history": [
            {
                "action": row.action,
                "action_label": row.get_action_display(),
                "by": row.user.full_name,
                "at": row.acted_at,
                "reason": row.reason,
            }
            for row in approvals.history(advances.DOC, a.pk)
        ],
    }
    return body


class AdvanceInput(serializers.Serializer):
    customer = serializers.IntegerField()
    quotation = serializers.IntegerField(required=False, allow_null=True)
    proforma = serializers.IntegerField(required=False, allow_null=True)
    division = serializers.CharField(max_length=2, required=False, allow_blank=True)
    account = serializers.IntegerField()
    method = serializers.CharField(max_length=10)
    amount = serializers.CharField(max_length=30)
    receipt_date = serializers.DateField()
    reference = serializers.CharField(max_length=50, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class AdvanceListView(_Advances):
    def get(self, request):
        rows = advances.visible(request.user).select_related(
            "customer", "quotation", "proforma", "division", "currency", "created_by"
        )
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("customer"):
            rows = rows.filter(customer_id=params["customer"])
        if params.get("waiting") == "me":
            waiting = approvals.waiting_for(request.user, advances.DOC)
            rows = rows.filter(pk__in=[state.document_id for state in waiting])
        return Response([_row(a) for a in rows[:2000]])

    def post(self, request):
        data = AdvanceInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        quotation = None
        if values.get("quotation"):
            quotation = Quotation.objects.filter(pk=values["quotation"]).first()
            if quotation is None:
                return _error("That quotation does not exist.")
        proforma = None
        if values.get("proforma"):
            proforma = ProformaInvoice.objects.filter(pk=values["proforma"]).first()
            if proforma is None:
                return _error("That proforma does not exist.")
        division = None
        if values.get("division"):
            division = Division.objects.filter(code=values["division"].upper()).first()
        try:
            advance = advances.record(
                request.user,
                customer=Customer.objects.filter(pk=values["customer"]).first(),
                account=CompanyAccount.objects.filter(pk=values["account"]).first(),
                method=values["method"],
                amount=values["amount"],
                receipt_date=values["receipt_date"],
                quotation=quotation,
                proforma=proforma,
                division=division,
                reference=values.get("reference", ""),
                notes=values.get("notes", ""),
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(advance, request.user), status=status.HTTP_201_CREATED)


class AdvanceOptionsView(_Advances):
    """What the Cashier chooses from: active customers with their approved quotations, the
    divisions they work in, and the accounts money is received into."""

    def get(self, request):
        issued = {}
        for p in ProformaInvoice.objects.filter(
            status=ProformaInvoice.Status.ISSUED
        ).select_related("currency"):
            issued.setdefault(p.customer_id, []).append(
                {
                    "id": p.id,
                    "number": p.number,
                    "currency": p.currency.code,
                    "total_amount": str(p.total_amount),
                    "advance_amount": str(p.advance_amount),
                }
            )
        quotations = {}
        for q in Quotation.objects.filter(status__in=advances.QUOTATION_OPEN).select_related(
            "currency"
        ):
            quotations.setdefault(q.customer_id, []).append(
                {
                    "id": q.id,
                    "label": q.label,
                    "division": q.division_id,
                    "currency": q.currency.code,
                    "total_amount": str(q.total_amount),
                }
            )
        return Response(
            {
                "can_record": advances.can_record(request.user),
                "customers": [
                    {
                        "id": c.id,
                        "code": c.code,
                        "name": c.name,
                        "quotations": quotations.get(c.id, []),
                        "proformas": issued.get(c.id, []),
                    }
                    for c in Customer.objects.filter(is_active=True).order_by("name")
                ],
                "divisions": [
                    {"code": d.code, "name": d.name}
                    for d in division_scope(request.user).filter(is_active=True)
                ],
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


class AdvanceDetailView(_Advances):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk), request.user))


class _Decision(_Advances):
    # The approval engine decides who may act (the Accountant, never on their own receipt).
    access_write_level = "view"


class AdvanceApproveView(_Decision):
    def post(self, request, pk):
        advance = _get(request.user, pk)
        try:
            advance = advances.approve(request.user, advance, str(request.data.get("comment", "")))
        except SalesError as error:
            return _error(error)
        return Response(_detail(CustomerAdvance.objects.get(pk=advance.pk), request.user))


class AdvanceRejectView(_Decision):
    def post(self, request, pk):
        advance = _get(request.user, pk)
        try:
            advance = advances.reject(request.user, advance, str(request.data.get("reason", "")))
        except SalesError as error:
            return _error(error)
        return Response(_detail(CustomerAdvance.objects.get(pk=advance.pk), request.user))


class AdvanceReceiptView(_Advances):
    def get(self, request, pk):
        advance = _get(request.user, pk)
        response = HttpResponse(receipt.render(advance), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="Receipt {advance.number}.pdf"'
        return response
