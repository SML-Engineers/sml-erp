"""Proforma invoices API (P15-08). Rules live in proformas.py; every endpoint checks Sales
access and returns only proformas the user may see."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess
from apps.masters.models import CompanyAccount

from . import proforma_email, proforma_printing, proformas
from .models import ProformaInvoice, QuotationLine
from .services import SalesError
from .services import visible as visible_quotations


class _Sales(APIView):
    permission_classes = [AreaAccess]
    access_area = "sales"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _get(user, pk) -> ProformaInvoice:
    return get_object_or_404(proformas.visible(user), pk=pk)


def _text(value):
    return None if value is None else str(value)


def _summary(p: ProformaInvoice) -> dict:
    return {
        "id": p.id,
        "number": p.number,
        "issue_date": p.issue_date,
        "status": p.status,
        "division": p.division.code,
        "customer": {"id": p.customer_id, "code": p.customer.code, "name": p.customer.name},
        "quotation": {"id": p.quotation_id, "label": p.quotation.label},
        "currency": p.currency.code,
        "total_amount": str(p.total_amount),
        "total_lkr": str(p.total_lkr),
        "created_by": p.created_by.full_name,
    }


def _detail(p: ProformaInvoice, user) -> dict:
    body = _summary(p)
    totals = proformas.packing_totals(p)
    body |= {
        "contact": None if p.contact is None else {"id": p.contact_id, "name": p.contact.name},
        "exchange_rate": str(p.exchange_rate),
        "rate_date": p.rate_date,
        "customer_po": p.customer_po,
        "payment_terms": p.payment_terms,
        "delivery_lead_time": p.delivery_lead_time,
        "incoterm": p.incoterm,
        "port_of_loading": p.port_of_loading,
        "port_of_destination": p.port_of_destination,
        "bank_account": None
        if p.bank_account is None
        else {"id": p.bank_account_id, "code": p.bank_account.code, "name": p.bank_account.name},
        "advance_pct": str(p.advance_pct),
        "advance_amount": str(p.advance_amount),
        "notes": p.notes,
        "discount_pct": str(p.discount_pct),
        "discount_total": str(p.discount_total),
        "subtotal": str(p.subtotal),
        "tax_total": str(p.tax_total),
        "cancel_reason": p.cancel_reason,
        "lines": [
            {
                "line_no": line.line_no,
                "quotation_line": line.quotation_line_id,
                "description": line.description,
                "drawing_no": line.drawing_no,
                "quantity": str(line.quantity),
                "unit": line.unit,
                "unit_price": str(line.unit_price),
                "is_tooling": line.is_tooling,
                "amount": str(line.amount),
                "discount": str(line.discount),
                "tax_amount": str(line.tax_amount),
                "total": str(line.total),
                **{
                    name: _text(getattr(line, name))
                    for name in (
                        "cartons",
                        "qty_per_carton",
                        "net_weight_kg",
                        "gross_weight_kg",
                        "carton_length_cm",
                        "carton_width_cm",
                        "carton_height_cm",
                    )
                },
                "volume_m3": _text(proformas.volume_m3(line)),
            }
            for line in p.lines.all()
        ],
        "packing_totals": {key: _text(value) for key, value in totals.items()},
        # The quotation's lines it can be made of, with their prices and breaks.
        "quotation_lines": [
            {
                "id": line.id,
                "line_no": line.line_no,
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "breaks": [
                    {"quantity": str(b.quantity), "unit_price": str(b.unit_price)}
                    for b in line.breaks.all()
                ],
            }
            for line in p.quotation.lines.prefetch_related("breaks")
        ],
        "can_edit": proformas.can_edit(user, p),
        "can_cancel": proformas.can_cancel(user, p),
        "can_email": proformas.can_email(user, p),
        "emails": proforma_email.history(p),
        "advances": [
            {"id": a.id, "number": a.number, "status": a.status, "amount": str(a.amount)}
            for a in p.advances.all()
        ],
    }
    return body


class PackingFields(serializers.Serializer):
    quotation_line = serializers.IntegerField()
    quantity = serializers.CharField(max_length=30)
    cartons = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    qty_per_carton = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    net_weight_kg = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    gross_weight_kg = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    carton_length_cm = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    carton_width_cm = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    carton_height_cm = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )


class ProformaInput(serializers.Serializer):
    customer_po = serializers.CharField(max_length=50, required=False, allow_blank=True)
    payment_terms = serializers.CharField(max_length=200, required=False, allow_blank=True)
    delivery_lead_time = serializers.CharField(max_length=100, required=False, allow_blank=True)
    incoterm = serializers.CharField(max_length=3, required=False, allow_blank=True)
    port_of_loading = serializers.CharField(max_length=100, required=False, allow_blank=True)
    port_of_destination = serializers.CharField(max_length=100, required=False, allow_blank=True)
    bank_account = serializers.IntegerField(required=False, allow_null=True)
    advance_pct = serializers.CharField(
        max_length=10, required=False, allow_blank=True, allow_null=True
    )
    discount_pct = serializers.CharField(
        max_length=10, required=False, allow_blank=True, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)
    lines = PackingFields(many=True)


class ProformaListView(_Sales):
    def get(self, request):
        rows = proformas.visible(request.user).select_related(
            "division", "customer", "quotation", "currency", "created_by"
        )
        if request.query_params.get("status"):
            rows = rows.filter(status__in=request.query_params["status"].split(","))
        if request.query_params.get("quotation"):
            rows = rows.filter(quotation_id=request.query_params["quotation"])
        return Response([_summary(p) for p in rows[:2000]])

    def post(self, request):
        quotation_id = request.data.get("quotation")
        quotation = visible_quotations(request.user).filter(pk=quotation_id).first()
        if quotation is None:
            return _error("Choose one of your accepted quotations.")
        try:
            made = proformas.create(request.user, quotation)
        except SalesError as error:
            return _error(error)
        return Response(_detail(made, request.user), status=status.HTTP_201_CREATED)


class ProformaDetailView(_Sales):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk), request.user))

    def put(self, request, pk):
        proforma = _get(request.user, pk)
        data = ProformaInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        lines = []
        for row in values.pop("lines"):
            source = QuotationLine.objects.filter(pk=row.pop("quotation_line")).first()
            lines.append(proformas.LineInput(quotation_line=source, **row))
        if "bank_account" in values:
            pk_ = values["bank_account"]
            values["bank_account"] = (
                None if pk_ is None else CompanyAccount.objects.filter(pk=pk_).first() or "unknown"
            )
        try:
            proforma = proformas.save(request.user, proforma, lines=lines, **values)
        except SalesError as error:
            return _error(error)
        return Response(_detail(ProformaInvoice.objects.get(pk=proforma.pk), request.user))


class ProformaIssueView(_Sales):
    def post(self, request, pk):
        proforma = _get(request.user, pk)
        try:
            proforma = proformas.issue(request.user, proforma)
        except SalesError as error:
            return _error(error)
        return Response(_detail(proforma, request.user))


class ProformaCancelView(_Sales):
    # The creator (Sales: Enter) or the Sales Manager (Sales: Approve); the service decides.
    access_write_level = "view"

    def post(self, request, pk):
        proforma = _get(request.user, pk)
        try:
            proforma = proformas.cancel(request.user, proforma, str(request.data.get("reason", "")))
        except SalesError as error:
            return _error(error)
        return Response(_detail(proforma, request.user))


class ProformaPdfView(_Sales):
    def get(self, request, pk):
        proforma = _get(request.user, pk)
        response = HttpResponse(proforma_printing.render(proforma), content_type="application/pdf")
        disposition = "attachment" if request.query_params.get("download") else "inline"
        response["Content-Disposition"] = (
            f'{disposition}; filename="Proforma-{proforma.number}.pdf"'
        )
        return response


class EmailInput(serializers.Serializer):
    to = serializers.ListField(child=serializers.CharField(max_length=254), max_length=20)
    cc = serializers.ListField(
        child=serializers.CharField(max_length=254), max_length=20, required=False
    )
    subject = serializers.CharField(max_length=200)
    body = serializers.CharField(max_length=20000)


class ProformaEmailView(_Sales):
    access_write_level = "view"

    def get(self, request, pk):
        proforma = _get(request.user, pk)
        try:
            return Response(proforma_email.draft(request.user, proforma))
        except SalesError as error:
            return _error(error)

    def post(self, request, pk):
        proforma = _get(request.user, pk)
        data = EmailInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        try:
            record = proforma_email.send(
                request.user,
                proforma,
                to=values["to"],
                cc=values.get("cc", []),
                subject=values["subject"],
                body=values["body"],
            )
        except SalesError as error:
            return _error(error)
        body = _detail(proforma, request.user)
        if record.status != "sent":
            body["email_error"] = f"The email could not be sent: {record.error}"
            return Response(body, status=status.HTTP_502_BAD_GATEWAY)
        return Response(body)
