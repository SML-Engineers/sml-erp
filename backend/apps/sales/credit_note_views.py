"""Credit notes API (P2-06). Rules live in credit_notes.py. Sales or Accounting: View to read,
Enter to make; approving is checked by the approval engine (the Director, or a person given
the right)."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.permissions import AreaAccess

from . import credit_note_printing, credit_notes, invoices
from .models import CreditNote, TaxInvoice
from .services import SalesError


class _Credits(APIView):
    permission_classes = [AreaAccess]
    access_area = "sales"
    access_also_area = "accounting"
    access_write_level = "enter"


class _Decide(_Credits):
    # The approver may be the Director (Sales: Approve, Accounting: View) or a person given
    # the right; the engine decides.
    access_write_level = "view"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _get(user, pk) -> CreditNote:
    rows = credit_notes.visible(user).select_related(
        "invoice", "customer", "division", "created_by", "journal_entry"
    )
    return get_object_or_404(rows, pk=pk)


def _summary(n: CreditNote) -> dict:
    return {
        "id": n.pk,
        "number": n.number,
        "status": n.status,
        "status_label": n.get_status_display(),
        "kind": n.kind,
        "credit_date": n.credit_date,
        "invoice": {"id": n.invoice_id, "number": n.invoice.number},
        "customer": {"id": n.customer_id, "name": n.customer.name},
        "division": n.division.code,
        "total_amount": f"{n.total_amount:.2f}",
        "created_by": n.created_by.full_name,
    }


def _invoice_lines(invoice: TaxInvoice, note: CreditNote | None) -> list[dict]:
    room = credit_notes.left(invoice, besides=note)
    here = {} if note is None else {x.invoice_line_id: x for x in note.lines.all()}
    return [
        {
            "id": line.pk,
            "line_no": line.line_no,
            "product_code": line.product_code,
            "description": line.description,
            "unit": line.unit,
            "quantity": f"{line.quantity:.3f}",
            "net": f"{line.net:.2f}",
            "tax_code": line.tax_code.code if line.tax_code else None,
            "left_amount": f"{room[line.pk]['amount']:.2f}",
            "left_quantity": f"{room[line.pk]['quantity']:.3f}",
            "credit_amount": f"{here[line.pk].amount:.2f}" if line.pk in here else None,
            "credit_quantity": f"{here[line.pk].quantity:.3f}" if line.pk in here else None,
            "credit_tax": f"{here[line.pk].tax_amount:.2f}" if line.pk in here else None,
        }
        for line in invoice.lines.select_related("tax_code")
    ]


def _detail(n: CreditNote, user) -> dict:
    body = _summary(n)
    state = approvals.state_of(credit_notes.DOC, n.pk)
    body |= {
        "reason": n.reason,
        "invoice_date": n.invoice.invoice_date,
        "subtotal": f"{n.subtotal:.2f}",
        "tax_total": f"{n.tax_total:.2f}",
        "amount_in_words": n.amount_in_words,
        "lines": _invoice_lines(n.invoice, n),
        "taxes": [
            {
                "label": t.label,
                "rate": f"{t.rate.normalize():f}",
                "on_tax": t.on_tax,
                "amount": f"{t.amount:.2f}",
            }
            for t in n.taxes.all()
        ],
        "journal_entry": None
        if n.journal_entry is None
        else {"id": n.journal_entry_id, "number": n.journal_entry.number},
        "can_edit": credit_notes.can_edit(user, n),
        "can_approve": credit_notes.can_approve(user, n),
        "approval": None
        if state is None
        else {
            "status": state.status,
            "history": [
                {
                    "action": row.action,
                    "action_label": row.get_action_display(),
                    "by": row.user.full_name,
                    "at": row.created_at,
                    "reason": row.reason,
                }
                for row in approvals.history(credit_notes.DOC, n.pk)
            ],
        },
    }
    return body


class LineIn(serializers.Serializer):
    invoice_line = serializers.IntegerField()
    amount = serializers.CharField(max_length=30, allow_blank=True)
    quantity = serializers.CharField(max_length=30, allow_blank=True, required=False)


class NoteIn(serializers.Serializer):
    invoice = serializers.IntegerField(required=False)
    kind = serializers.CharField(max_length=10)
    reason = serializers.CharField(max_length=1000, allow_blank=True)
    credit_date = serializers.DateField(required=False)
    lines = LineIn(many=True)


def _lines(invoice: TaxInvoice, rows) -> list[credit_notes.LineInput]:
    by_id = {line.pk: line for line in invoice.lines.all()}
    result = []
    for row in rows:
        if str(row.get("amount", "")).strip() in ("", "0"):
            continue
        line = by_id.get(row["invoice_line"])
        if line is None:
            raise SalesError("A line is not on this invoice.")
        result.append(
            credit_notes.LineInput(line, row["amount"], (row.get("quantity") or "0").strip())
        )
    return result


def _values(data) -> dict:
    return {k: data[k] for k in ("kind", "reason", "credit_date") if k in data}


class CreditListView(_Credits):
    """Credit notes, newest first. Filters: status, invoice, waiting=me."""

    def get(self, request):
        rows = credit_notes.visible(request.user).select_related(
            "invoice", "customer", "division", "created_by"
        )
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("invoice", "").isdigit():
            rows = rows.filter(invoice_id=int(params["invoice"]))
        if params.get("waiting") == "me":
            waiting = approvals.waiting_for(request.user, credit_notes.DOC)
            rows = rows.filter(pk__in=[s.document_id for s in waiting])
        return Response([_summary(n) for n in rows[:1000]])

    def post(self, request):
        body = NoteIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        invoice = get_object_or_404(invoices.visible(request.user), pk=data.get("invoice"))
        try:
            note = credit_notes.create(
                request.user, invoice, lines=_lines(invoice, data["lines"]), **_values(data)
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, note.pk), request.user), status=201)


class InvoiceLinesView(_Credits):
    """An issued invoice's lines and what is left to credit (for a new credit note)."""

    def get(self, request, pk):
        invoice = get_object_or_404(
            invoices.visible(request.user).filter(status=TaxInvoice.Status.ISSUED), pk=pk
        )
        return Response(
            {
                "id": invoice.pk,
                "number": invoice.number,
                "invoice_date": invoice.invoice_date,
                "customer": invoice.customer.name,
                "total_amount": f"{invoice.total_amount:.2f}",
                "lines": _invoice_lines(invoice, None),
            }
        )


class CreditDetailView(_Credits):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk), request.user))

    def put(self, request, pk):
        note = _get(request.user, pk)
        body = NoteIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            credit_notes.save(
                request.user, note, lines=_lines(note.invoice, data["lines"]), **_values(data)
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))

    def delete(self, request, pk):
        try:
            credit_notes.delete(request.user, _get(request.user, pk))
        except SalesError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CreditSubmitView(_Credits):
    def post(self, request, pk):
        try:
            credit_notes.submit(
                request.user, _get(request.user, pk), str(request.data.get("comment", ""))
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))


class CreditApproveView(_Decide):
    def post(self, request, pk):
        try:
            credit_notes.approve(
                request.user, _get(request.user, pk), str(request.data.get("comment", ""))
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))


class CreditReturnView(_Decide):
    def post(self, request, pk):
        try:
            credit_notes.send_back(
                request.user, _get(request.user, pk), str(request.data.get("reason", ""))
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))


class CreditRejectView(_Decide):
    def post(self, request, pk):
        try:
            credit_notes.reject(
                request.user, _get(request.user, pk), str(request.data.get("reason", ""))
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))


class CreditPdfView(_Credits):
    def get(self, request, pk):
        note = _get(request.user, pk)
        response = HttpResponse(credit_note_printing.render(note), content_type="application/pdf")
        name = note.number or f"draft-{note.pk}"
        disposition = "attachment" if request.query_params.get("download") else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="Credit-note-{name}.pdf"'
        return response
