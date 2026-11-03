"""Receivables API (P2-08): aging, customer statements (PDF, Excel, email), payment reminders
and credit holds. Rules live in receivables.py. Sales or Accounting: View to read; emailing
statements and reminders are the Accountant's; allowing a credit hold is the Director's (the
service checks each)."""

from datetime import date, timedelta

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import exports
from apps.core.exports import STRONG, Column
from apps.core.permissions import AreaAccess
from apps.masters.models import Customer

from . import receivables, statement_printing
from .models import CreditHold, ReminderPlan, ReminderSent
from .proforma_views import EmailInput
from .services import SalesError


class _Receivables(APIView):
    permission_classes = [AreaAccess]
    access_area = "sales"
    access_also_area = "accounting"
    # Writes are checked by the service (the Accountant, or the Director for holds).
    access_write_level = "view"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _day(request, name: str, default: date) -> date:
    value = request.query_params.get(name) or ""
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        return default


def _money(value) -> str:
    return f"{value:.2f}"


AGING_COLUMNS = [
    Column("code", "Code", width=0.8),
    Column("customer", "Customer", width=2.4),
    *[Column(key, label, "money") for key, label in receivables.BUCKETS],
    Column("total", "Total open", "money"),
    Column("ledger", "Ledger balance", "money"),
]


class AgingView(_Receivables):
    """?as_at=YYYY-MM-DD (default today), ?customer=id, ?export=xlsx|pdf."""

    def get(self, request):
        as_at = _day(request, "as_at", timezone.localdate())
        customer = None
        if request.query_params.get("customer"):
            customer = Customer.objects.filter(pk=request.query_params["customer"]).first()
        rows = receivables.aging(request.user, as_at, customer)
        fmt = (request.query_params.get("export") or "").lower()
        if fmt in exports.FORMATS:
            return exports.response(
                fmt,
                title="Receivables aging",
                subtitle=f"What customers owe on their invoices as at {as_at:%d/%m/%Y}, by days "
                "past the due date",
                columns=AGING_COLUMNS,
                rows=rows,
                filename=f"receivables-aging-{as_at:%Y-%m-%d}",
                user=request.user,
            )
        return Response({"as_at": as_at, "rows": rows})


STATEMENT_COLUMNS = [
    Column("date", "Date", "date", width=0.9),
    Column("reference", "Reference", width=1.2),
    Column("description", "Description", width=2.6),
    Column("debit", "Debit", "money"),
    Column("credit", "Credit", "money"),
    Column("balance", "Balance", "money"),
]


def _statement(request, customer: Customer):
    end = _day(request, "to", timezone.localdate())
    start = _day(request, "from", end - timedelta(days=90))
    return receivables.statement(request.user, customer, start, end)


def _plan(customer: Customer, user) -> dict:
    plan = ReminderPlan.objects.filter(customer=customer).select_related("set_by").first()
    last = ReminderSent.objects.filter(customer=customer).select_related("email").first()
    return {
        "is_on": bool(plan and plan.is_on),
        "every_days": plan.every_days if plan else 7,
        "set_by": plan.set_by.full_name if plan else None,
        "recipient": receivables.recipient(customer),
        "last_sent_on": last.sent_on if last else None,
        "can_manage": receivables.can_manage(user),
    }


def _body(st, user) -> dict:
    customer = st.customer
    figures = receivables.exposure(customer)
    return {
        "customer": {
            "id": customer.pk,
            "code": customer.code,
            "name": customer.name,
            "credit_limit": None
            if customer.credit_limit is None
            else _money(customer.credit_limit),
            "payment_terms_days": customer.payment_terms_days,
        },
        "from": st.start,
        "to": st.end,
        "opening": _money(st.opening),
        "closing": _money(st.closing),
        "lines": [
            {
                **line,
                "debit": _money(line["debit"]),
                "credit": _money(line["credit"]),
                "balance": _money(line["balance"]),
            }
            for line in st.lines
        ],
        "items": [
            {
                "invoice": {
                    "id": item["invoice"].pk,
                    "number": item["invoice"].number,
                    "invoice_date": item["invoice"].invoice_date,
                    "due_date": item["invoice"].due_date,
                    "total_amount": _money(item["invoice"].total_amount),
                },
                "open": _money(item["open"]),
                "days_overdue": max(item["days_overdue"], 0),
                "bucket": item["bucket"],
            }
            for item in st.items
        ],
        "buckets": {key: _money(value) for key, value in st.buckets.items()},
        "overdue": _money(st.overdue),
        "advances_held": _money(st.advances_held),
        "credit": {
            "owed": _money(figures.owed),
            "overdue": _money(figures.overdue_lkr),
            "over_limit": customer.credit_limit is not None
            and figures.owed > customer.credit_limit,
            "on_hold": figures.overdue_lkr > 0
            or (customer.credit_limit is not None and figures.owed > customer.credit_limit),
        },
        "reminders": _plan(customer, user),
        "can_email": receivables.can_manage(user),
        "emails": receivables.emails(customer),
    }


class StatementView(_Receivables):
    """?from, ?to (default the last 90 days), ?export=pdf|xlsx."""

    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        try:
            st = _statement(request, customer)
        except SalesError as error:
            return _error(error)
        fmt = (request.query_params.get("export") or "").lower()
        if fmt == "pdf":
            reply = HttpResponse(statement_printing.render(st), content_type="application/pdf")
            reply["Content-Disposition"] = (
                f'inline; filename="Statement-{customer.code}-{st.end:%Y-%m-%d}.pdf"'
            )
            return reply
        if fmt == "xlsx":
            rows = [
                {"date": st.start, "description": "Opening balance", "balance": st.opening},
                *st.lines,
                {
                    "date": st.end,
                    "description": "Closing balance",
                    "balance": st.closing,
                    STRONG: True,
                },
            ]
            return exports.response(
                fmt,
                title=f"Statement of account: {customer.name} ({customer.code})",
                subtitle=f"{st.start:%d/%m/%Y} to {st.end:%d/%m/%Y}, LKR",
                columns=STATEMENT_COLUMNS,
                rows=rows,
                filename=f"statement-{customer.code}-{st.end:%Y-%m-%d}",
                user=request.user,
                totals=False,
            )
        return Response(_body(st, request.user))


class StatementEmailView(_Receivables):
    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        try:
            return Response(receivables.draft_email(request.user, _statement(request, customer)))
        except SalesError as error:
            return _error(error)

    def post(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        data = EmailInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        try:
            st = _statement(request, customer)
            sent = receivables.send_email(
                request.user,
                st,
                to=values["to"],
                cc=values.get("cc", []),
                subject=values["subject"],
                body=values["body"],
            )
        except SalesError as error:
            return _error(error)
        if sent.status != "sent":
            return _error(f"The email could not be sent: {sent.error}")
        return Response(_body(st, request.user))


class RemindersInput(serializers.Serializer):
    is_on = serializers.BooleanField()
    every_days = serializers.IntegerField()


class RemindersView(_Receivables):
    def put(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        data = RemindersInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            receivables.set_reminders(request.user, customer, **data.validated_data)
        except SalesError as error:
            return _error(error)
        return Response(_plan(customer, request.user))


def _hold(h: CreditHold, user) -> dict:
    return {
        "id": h.pk,
        "document_type": h.document_type,
        "document_label": h.document_label,
        "link": receivables.link(h),
        "customer": {"id": h.customer_id, "code": h.customer.code, "name": h.customer.name},
        "amount_lkr": _money(h.amount_lkr),
        "exposure_lkr": _money(h.exposure_lkr),
        "credit_limit": None if h.credit_limit is None else _money(h.credit_limit),
        "overdue_lkr": _money(h.overdue_lkr),
        "reasons": h.reasons,
        "status": h.status,
        "requested_by": h.requested_by.full_name,
        "requested_at": h.requested_at,
        "decided_by": h.decided_by.full_name if h.decided_by_id else None,
        "decided_at": h.decided_at,
        "note": h.note,
        "can_allow": h.status == CreditHold.Status.WAITING and receivables.can_allow(user),
    }


class CreditHoldListView(_Receivables):
    """?status=waiting|allowed."""

    def get(self, request):
        rows = CreditHold.objects.select_related("customer", "requested_by", "decided_by")
        if request.query_params.get("status"):
            rows = rows.filter(status=request.query_params["status"])
        return Response([_hold(h, request.user) for h in rows[:500]])


class AllowInput(serializers.Serializer):
    note = serializers.CharField(max_length=1000, allow_blank=True)


class CreditHoldAllowView(_Receivables):
    def post(self, request, pk):
        credit_hold = get_object_or_404(CreditHold, pk=pk)
        data = AllowInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            credit_hold = receivables.allow(request.user, credit_hold, data.validated_data["note"])
        except SalesError as error:
            return _error(error)
        return Response(_hold(CreditHold.objects.get(pk=credit_hold.pk), request.user))
