"""Supplier invoices API (P16-10). Rules live in invoices.py; reading needs Vouchers or
Accounting: View, for the user's divisions. Changes are checked by the service."""

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounting.models import TaxCode
from apps.core import approvals
from apps.core.models import Division
from apps.core.permissions import AreaAccess
from apps.masters.models import Supplier

from . import invoices
from .invoices import InvoiceError, LineInput
from .models import SupplierInvoice, SupplierInvoiceAttachment


class _Invoices(APIView):
    """Reading needs Vouchers: View (Clerk, Accountant, Director); the service checks the rest."""

    permission_classes = [AreaAccess]
    access_area = "vouchers"
    access_write_level = "view"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _summary(i: SupplierInvoice) -> dict:
    return {
        "id": i.id,
        "number": i.number,
        "invoice_no": i.invoice_no,
        "invoice_date": i.invoice_date,
        "due_date": i.due_date,
        "status": i.status,
        "division": i.division.code,
        "supplier": {"id": i.supplier_id, "code": i.supplier.code, "name": i.supplier.name},
        "currency": i.currency.code,
        "total_amount": str(i.total_amount),
        "total_lkr": str(i.total_lkr),
        "created_by": i.created_by.full_name,
    }


def _open_row(row) -> dict:
    line = row["line"]
    order = line.receipt.purchase_order
    return {
        "grn_line": line.id,
        "grn": {
            "id": line.receipt_id,
            "number": line.receipt.number,
            "date": line.receipt.receipt_date,
        },
        "po": {"id": order.id, "label": order.label, "currency": order.currency.code},
        "item": {"code": line.item.code, "name": line.item.name, "unit": line.item.unit},
        "accepted_quantity": str(invoices.accepted(line)),
        "open_quantity": str(row["open"]),
        "po_unit_price": str(line.po_line.unit_price),
        "po_tax_code": line.po_line.tax_code.code if line.po_line.tax_code else None,
    }


def _detail(i: SupplierInvoice, user) -> dict:
    return _summary(i) | {
        "stated_total": None if i.stated_total is None else str(i.stated_total),
        "subtotal": str(i.subtotal),
        "tax_total": str(i.tax_total),
        "discrepancies": i.discrepancies,
        "notes": i.notes,
        "exception_reason": i.exception_reason,
        "cancel_reason": i.cancel_reason,
        "journal": None if i.journal_entry_id is None else i.journal_entry.number,
        "posted_at": i.posted_at,
        "lines": [
            {
                "line_no": line.line_no,
                "grn_line": line.grn_line_id,
                "grn": {"id": line.grn_line.receipt_id, "number": line.grn_line.receipt.number},
                "po": {
                    "id": line.grn_line.receipt.purchase_order_id,
                    "label": line.grn_line.receipt.purchase_order.label,
                },
                "item": {"code": line.item.code, "name": line.item.name, "unit": line.item.unit},
                "quantity": str(line.quantity),
                "accepted_quantity": str(invoices.accepted(line.grn_line)),
                "unit_price": str(line.unit_price),
                "po_unit_price": str(line.po_unit_price),
                "tax_code": line.tax_code.code if line.tax_code else None,
                "po_tax_code": line.po_tax_code.code if line.po_tax_code else None,
                "amount": str(line.amount),
                "tax_amount": str(line.tax_amount),
                "total": str(line.total),
            }
            for line in i.lines.select_related(
                "grn_line__receipt__purchase_order", "item", "tax_code", "po_tax_code"
            )
        ],
        "attachments": [
            {
                "id": a.id,
                "file_name": a.file_name,
                "uploaded_by": a.uploaded_by.full_name,
                "uploaded_at": a.uploaded_at,
            }
            for a in i.attachments.select_related("uploaded_by").order_by("uploaded_at", "id")
        ],
        "can_edit": invoices.can_edit(user, i),
        "can_reopen": i.status == SupplierInvoice.Status.HELD and invoices.can_enter(user),
        "can_cancel": i.status == SupplierInvoice.Status.HELD and invoices.can_enter(user),
        "can_request_exception": i.status == SupplierInvoice.Status.HELD
        and invoices.can_request_exception(user),
        "can_approve": invoices.can_approve(user, i),
        "history": [
            {
                "action": row.action,
                "action_label": row.get_action_display(),
                "by": row.user.full_name,
                "at": row.acted_at,
                "reason": row.reason,
            }
            for row in approvals.history(invoices.DOC, i.pk)
        ],
    }


def _get(user, pk) -> SupplierInvoice:
    return get_object_or_404(invoices.visible(user), pk=pk)


def _fresh(i: SupplierInvoice, user) -> dict:
    return _detail(invoices.visible(user).select_related("journal_entry").get(pk=i.pk), user)


class LineIn(serializers.Serializer):
    grn_line = serializers.IntegerField()
    quantity = serializers.CharField(max_length=30)
    unit_price = serializers.CharField(max_length=30)
    tax_code = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )


class InvoiceIn(serializers.Serializer):
    invoice_no = serializers.CharField(max_length=50, allow_blank=True)
    invoice_date = serializers.DateField()
    stated_total = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)
    lines = LineIn(many=True)


def _lines(rows) -> list[LineInput]:
    result = []
    for n, row in enumerate(rows, start=1):
        code = (row.get("tax_code") or "").strip().upper()
        tax = None
        if code:
            tax = TaxCode.objects.filter(code=code).first()
            if tax is None:
                raise InvoiceError(f"Line {n}: there is no tax code {code}.")
        result.append(LineInput(row["grn_line"], row["quantity"], row["unit_price"], tax))
    return result


class OpenLinesView(_Invoices):
    """Accepted goods of a supplier not yet invoiced, to choose an invoice's lines from."""

    def get(self, request):
        supplier = Supplier.objects.filter(pk=request.query_params.get("supplier")).first()
        division = Division.objects.filter(
            code=str(request.query_params.get("division", "")).upper()
        ).first()
        if supplier is None or division is None:
            return Response([])
        return Response(
            [_open_row(r) for r in invoices.open_lines(request.user, supplier, division)]
        )


class InvoiceListView(_Invoices):
    def get(self, request):
        rows = invoices.visible(request.user)
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("supplier"):
            rows = rows.filter(supplier_id=params["supplier"])
        if params.get("waiting") == "me":
            ids = [s.document_id for s in approvals.waiting_for(request.user, invoices.DOC)]
            rows = rows.filter(pk__in=ids)
        return Response([_summary(i) for i in rows[:2000]])

    def post(self, request):
        body = InvoiceIn(data=request.data)
        body.is_valid(raise_exception=True)
        values = dict(body.validated_data)
        try:
            invoice = invoices.create(
                request.user,
                supplier=Supplier.objects.filter(pk=request.data.get("supplier")).first(),
                division=Division.objects.filter(
                    code=str(request.data.get("division", "")).upper()
                ).first(),
                lines=_lines(values.pop("lines")),
                **values,
            )
        except InvoiceError as error:
            return _error(error)
        return Response(_fresh(invoice, request.user), status=status.HTTP_201_CREATED)


class InvoiceDetailView(_Invoices):
    def get(self, request, pk):
        return Response(_fresh(_get(request.user, pk), request.user))

    def put(self, request, pk):
        invoice = _get(request.user, pk)
        body = InvoiceIn(data=request.data)
        body.is_valid(raise_exception=True)
        values = dict(body.validated_data)
        try:
            invoices.save(request.user, invoice, lines=_lines(values.pop("lines")), **values)
        except InvoiceError as error:
            return _error(error)
        return Response(_fresh(invoice, request.user))

    def delete(self, request, pk):
        try:
            invoices.delete(request.user, _get(request.user, pk))
        except InvoiceError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _text(request, name: str) -> str:
    return str(request.data.get(name, ""))


class _Action(_Invoices):
    def _run(self, request, pk, action):
        invoice = _get(request.user, pk)
        try:
            action(invoice)
        except InvoiceError as error:
            return _error(error)
        return Response(_fresh(invoice, request.user))


class MatchView(_Action):
    def post(self, request, pk):
        return self._run(request, pk, lambda i: invoices.match(request.user, i))


class ReopenView(_Action):
    def post(self, request, pk):
        return self._run(request, pk, lambda i: invoices.back_to_draft(request.user, i))


class ExceptionView(_Action):
    def post(self, request, pk):
        return self._run(
            request,
            pk,
            lambda i: invoices.request_exception(request.user, i, _text(request, "reason")),
        )


class ApproveView(_Action):
    def post(self, request, pk):
        return self._run(
            request,
            pk,
            lambda i: invoices.approve_exception(request.user, i, _text(request, "comment")),
        )


class ReturnView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda i: invoices.send_back(request.user, i, _text(request, "reason"))
        )


class CancelView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda i: invoices.cancel(request.user, i, _text(request, "reason"))
        )


class AttachmentListView(_Invoices):
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        invoice = _get(request.user, pk)
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose a file to attach.")
        try:
            invoices.add_attachment(request.user, invoice, uploaded)
        except InvoiceError as error:
            return _error(error)
        return Response(_fresh(invoice, request.user), status=status.HTTP_201_CREATED)


class AttachmentDetailView(_Invoices):
    def get(self, request, pk, attachment_pk):
        invoice = _get(request.user, pk)
        attachment = get_object_or_404(SupplierInvoiceAttachment, pk=attachment_pk, invoice=invoice)
        return FileResponse(
            attachment.file.open("rb"),
            content_type=attachment.content_type,
            filename=attachment.file_name,
            as_attachment=request.query_params.get("download") in ("1", "true"),
        )

    def delete(self, request, pk, attachment_pk):
        invoice = _get(request.user, pk)
        attachment = get_object_or_404(SupplierInvoiceAttachment, pk=attachment_pk, invoice=invoice)
        try:
            invoices.remove_attachment(request.user, attachment)
        except InvoiceError as error:
            return _error(error)
        return Response(_fresh(invoice, request.user))
