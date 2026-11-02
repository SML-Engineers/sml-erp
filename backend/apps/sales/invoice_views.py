"""Tax invoices API (P2-05). Rules live in invoices.py. Sales or Accounting (View to read;
Sales or Accounting: Enter to prepare; the Accountant issues)."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounting.models import Account
from apps.core.models import Division
from apps.core.permissions import AreaAccess

from . import invoice_email, invoice_printing, invoices
from .models import DeliveryNote, TaxInvoice
from .proforma_views import EmailInput
from .services import SalesError


class _Invoices(APIView):
    permission_classes = [AreaAccess]
    access_area = "sales"
    access_also_area = "accounting"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _get(user, pk) -> TaxInvoice:
    rows = invoices.visible(user).select_related(
        "order", "customer", "division", "created_by", "issued_by", "journal_entry"
    )
    return get_object_or_404(rows, pk=pk)


def _summary(i: TaxInvoice) -> dict:
    return {
        "id": i.pk,
        "number": i.number,
        "status": i.status,
        "invoice_date": i.invoice_date,
        "due_date": i.due_date,
        "division": i.division.code,
        "customer": {"id": i.customer_id, "name": i.customer.name},
        "order": {"id": i.order_id, "number": i.order.number},
        "customer_po": i.customer_po,
        "total_amount": f"{i.total_amount:.2f}",
        "created_by": i.created_by.full_name,
    }


def _detail(i: TaxInvoice, user) -> dict:
    body = _summary(i)
    lines = list(i.lines.select_related("delivery_line__note", "tax_code", "account"))
    body |= {
        "supply_date": i.supply_date,
        "place_of_supply": i.place_of_supply,
        "terms": i.terms,
        "notes": i.notes,
        "customer_tin": i.customer_tin if i.status == "issued" else i.customer.tin,
        "subtotal": f"{i.subtotal:.2f}",
        "discount_total": f"{i.discount_total:.2f}",
        "tax_total": f"{i.tax_total:.2f}",
        "amount_in_words": i.amount_in_words,
        "lines": [
            {
                "line_no": x.line_no,
                "delivery_note": {
                    "id": x.delivery_line.note_id,
                    "number": x.delivery_line.note.number,
                },
                "product_code": x.product_code,
                "description": x.description,
                "po_no": x.po_no,
                "unit": x.unit,
                "quantity": f"{x.quantity:.3f}",
                "rate": f"{x.rate:.2f}",
                "amount": f"{x.amount:.2f}",
                "discount": f"{x.discount:.2f}",
                "tax_code": x.tax_code.code if x.tax_code else None,
                "tax_amount": f"{x.tax_amount:.2f}",
                "account": {"id": x.account_id, "number": x.account.number, "name": x.account.name},
            }
            for x in lines
        ],
        "taxes": [
            {
                "label": t.label,
                "rate": f"{t.rate.normalize():f}",
                "on_tax": t.on_tax,
                "amount": f"{t.amount:.2f}",
            }
            for t in i.taxes.all()
        ],
        "journal_entry": None
        if i.journal_entry is None
        else {"id": i.journal_entry_id, "number": i.journal_entry.number},
        "issued_by": i.issued_by.full_name if i.issued_by else None,
        "issued_at": i.issued_at,
        "can_edit": invoices.can_edit(user, i),
        "can_issue": invoices.can_issue(user, i),
        "can_email": invoice_email.can_email(user, i),
        "emails": invoice_email.history(i),
    }
    return body


class InvoiceIn(serializers.Serializer):
    order = serializers.IntegerField()
    delivery_notes = serializers.ListField(
        child=serializers.IntegerField(), required=False, max_length=200
    )


class HeaderIn(serializers.Serializer):
    invoice_date = serializers.DateField(required=False)
    supply_date = serializers.DateField(required=False)
    place_of_supply = serializers.CharField(max_length=200, allow_blank=True, required=False)
    terms = serializers.CharField(max_length=200, allow_blank=True, required=False)
    notes = serializers.CharField(max_length=2000, allow_blank=True, required=False)


class InvoiceListView(_Invoices):
    """Tax invoices, newest first. Filters: status, order."""

    def get(self, request):
        rows = invoices.visible(request.user).select_related(
            "order", "customer", "division", "created_by"
        )
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("order", "").isdigit():
            rows = rows.filter(order_id=int(params["order"]))
        return Response([_summary(i) for i in rows[:1000]])

    def post(self, request):
        body = InvoiceIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        order = get_object_or_404(invoices.orders_to_invoice(request.user), pk=data["order"])
        notes = None
        if data.get("delivery_notes"):
            notes = list(DeliveryNote.objects.filter(order=order, pk__in=data["delivery_notes"]))
        try:
            made = invoices.create(request.user, order, notes)
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, made.pk), request.user), status=201)


class OrdersToInvoiceView(_Invoices):
    """Orders with delivered quantities waiting to be invoiced, and their delivery notes."""

    def get(self, request):
        rows = invoices.orders_to_invoice(request.user).select_related("customer", "division")
        result = []
        for o in rows.order_by("order_date", "number")[:500]:
            notes = (
                DeliveryNote.objects.filter(
                    order=o, status__in=invoices.DELIVERED, lines__invoice_line__isnull=True
                )
                .distinct()
                .order_by("delivery_date", "number")
            )
            result.append(
                {
                    "id": o.pk,
                    "number": o.number,
                    "division": o.division.code,
                    "customer": o.customer.name,
                    "customer_po": o.customer_po,
                    "currency": o.currency.code,
                    "delivery_notes": [
                        {"id": n.pk, "number": n.number, "delivery_date": n.delivery_date}
                        for n in notes
                    ],
                }
            )
        return Response(result)


class InvoiceDetailView(_Invoices):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk), request.user))

    def put(self, request, pk):
        invoice = _get(request.user, pk)
        body = HeaderIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            invoices.save(request.user, invoice, invoices.Header(**body.validated_data))
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))

    def delete(self, request, pk):
        try:
            invoices.delete(request.user, _get(request.user, pk))
        except SalesError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvoiceIssueView(_Invoices):
    def post(self, request, pk):
        try:
            invoices.issue(request.user, _get(request.user, pk))
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))


class InvoicePdfView(_Invoices):
    def get(self, request, pk):
        invoice = _get(request.user, pk)
        response = HttpResponse(invoice_printing.render(invoice), content_type="application/pdf")
        disposition = "attachment" if request.query_params.get("download") else "inline"
        name = invoice.number or f"draft-{invoice.pk}"
        response["Content-Disposition"] = f'{disposition}; filename="Tax-invoice-{name}.pdf"'
        return response


class InvoiceEmailView(_Invoices):
    access_write_level = "view"

    def get(self, request, pk):
        try:
            return Response(invoice_email.draft(request.user, _get(request.user, pk)))
        except SalesError as error:
            return _error(error)

    def post(self, request, pk):
        invoice = _get(request.user, pk)
        data = EmailInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        try:
            record = invoice_email.send(
                request.user,
                invoice,
                to=values["to"],
                cc=values.get("cc", []),
                subject=values["subject"],
                body=values["body"],
            )
        except SalesError as error:
            return _error(error)
        body = _detail(invoice, request.user)
        if record.status != "sent":
            body["email_error"] = f"The email could not be sent: {record.error}"
            return Response(body, status=status.HTTP_502_BAD_GATEWAY)
        return Response(body)


def _account(a: Account) -> dict:
    return {"id": a.pk, "number": a.number, "name": a.name}


class SalesAccountsView(APIView):
    """The income accounts per division (Accounting: View; changes need Manage)."""

    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "manage"

    def get(self, request):
        rows = {r.division_id: r for r in invoices.sales_accounts()}
        return Response(
            [
                {
                    "division": {"code": d.code, "name": d.name},
                    "account": _account(rows[d.pk].account) if d.pk in rows else None,
                    "tooling_account": _account(rows[d.pk].tooling_account)
                    if d.pk in rows
                    else None,
                }
                for d in Division.objects.order_by("code")
            ]
        )

    def put(self, request):
        division = get_object_or_404(Division, code=str(request.data.get("division", "")))
        account = get_object_or_404(Account, pk=request.data.get("account"))
        tooling = get_object_or_404(Account, pk=request.data.get("tooling_account"))
        try:
            invoices.set_sales_account(request.user, division, account, tooling)
        except SalesError as error:
            return _error(error)
        return self.get(request)
