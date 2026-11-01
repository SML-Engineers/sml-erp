"""Supplier returns API (P16-12). Rules live in returns.py; reading needs Stores: View, for
the user's divisions; changes are checked by the service."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.permissions import AreaAccess
from apps.inventory import receipts as grns
from apps.inventory.models import GoodsReceiptLine

from . import returns
from .models import SupplierReturn
from .returns import LineInput, ReturnError


class _Returns(APIView):
    permission_classes = [AreaAccess]
    access_area = "stores"
    access_write_level = "view"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _summary(r: SupplierReturn) -> dict:
    return {
        "id": r.id,
        "number": r.number,
        "kind": r.kind,
        "status": r.status,
        "return_date": r.return_date,
        "division": r.division.code,
        "supplier": {"id": r.supplier_id, "code": r.supplier.code, "name": r.supplier.name},
        "grn": {"id": r.receipt_id, "number": r.receipt.number},
        "reason": r.reason,
        "created_by": r.created_by.full_name,
    }


def _lots(grn, kind) -> list[dict]:
    lines = GoodsReceiptLine.objects.select_related("item").in_bulk(
        [row["receipt_line"] for row in returns.lots(grn, kind)]
    )
    return [
        {
            "grn_line": row["receipt_line"],
            "lot_no": row["lot_no"],
            "item": {
                "code": lines[row["receipt_line"]].item.code,
                "name": lines[row["receipt_line"]].item.name,
                "unit": lines[row["receipt_line"]].item.unit,
            },
            "quantity": str(row["quantity"]),
            "value": str(row["value"]),
        }
        for row in returns.lots(grn, kind)
    ]


def _detail(r: SupplierReturn, user) -> dict:
    return _summary(r) | {
        "vehicle_no": r.vehicle_no,
        "confirmed_at": r.confirmed_at,
        "journal": None if r.journal_entry_id is None else r.journal_entry.number,
        "lines": [
            {
                "line_no": line.line_no,
                "grn_line": line.grn_line_id,
                "lot_no": line.lot_no,
                "item": {
                    "code": line.grn_line.item.code,
                    "name": line.grn_line.item.name,
                    "unit": line.grn_line.item.unit,
                },
                "quantity": str(line.quantity),
                "uninvoiced_quantity": str(line.uninvoiced_quantity),
                "invoiced_quantity": str(line.invoiced_quantity),
                "value": str(line.value),
            }
            for line in r.lines.select_related("grn_line__item")
        ],
        "debit_notes": [
            {
                "number": d.number,
                "invoice": {"id": d.invoice_id, "invoice_no": d.invoice.invoice_no},
                "quantity": str(d.quantity),
                "total_lkr": str(d.total_lkr),
            }
            for d in r.debit_notes.select_related("invoice")
        ],
        "available": _lots(r.receipt, r.kind) if r.status == SupplierReturn.Status.DRAFT else [],
        "can_edit": returns.can_edit(user, r),
        "can_approve": returns.can_approve(user, r),
        "history": [
            {
                "action": row.action,
                "action_label": row.get_action_display(),
                "by": row.user.full_name,
                "at": row.acted_at,
                "reason": row.reason,
            }
            for row in approvals.history(returns.DOC, r.pk)
        ],
    }


def _get(user, pk) -> SupplierReturn:
    return get_object_or_404(returns.visible(user), pk=pk)


def _fresh(r, user) -> dict:
    return _detail(returns.visible(user).select_related("journal_entry").get(pk=r.pk), user)


class LineIn(serializers.Serializer):
    grn_line = serializers.IntegerField()
    lot_no = serializers.CharField(max_length=40)
    quantity = serializers.CharField(max_length=30)


class ReturnIn(serializers.Serializer):
    reason = serializers.CharField(max_length=2000, allow_blank=True)
    vehicle_no = serializers.CharField(max_length=30, required=False, allow_blank=True)
    return_date = serializers.DateField(required=False)
    lines = LineIn(many=True)


def _lines(rows) -> list[LineInput]:
    return [LineInput(r["grn_line"], r["lot_no"], r["quantity"]) for r in rows]


class LotsView(_Returns):
    """What can be returned from a GRN: its lots still in the rejected or main store."""

    def get(self, request):
        grn = grns.visible(request.user).filter(pk=request.query_params.get("grn")).first()
        kind = request.query_params.get("kind", "")
        if grn is None or kind not in SupplierReturn.Kind.values:
            return Response([])
        return Response(_lots(grn, kind))


class ReturnListView(_Returns):
    def get(self, request):
        rows = returns.visible(request.user)
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("waiting") == "me":
            ids = [s.document_id for s in approvals.waiting_for(request.user, returns.DOC)]
            rows = rows.filter(pk__in=ids)
        return Response([_summary(r) for r in rows[:2000]])

    def post(self, request):
        body = ReturnIn(data=request.data)
        body.is_valid(raise_exception=True)
        values = dict(body.validated_data)
        grn = grns.visible(request.user).filter(pk=request.data.get("grn")).first()
        if grn is None:
            return _error("Choose a confirmed GRN.")
        try:
            made = returns.create(
                request.user,
                grn,
                kind=str(request.data.get("kind", "")),
                lines=_lines(values.pop("lines")),
                **values,
            )
        except ReturnError as error:
            return _error(error)
        return Response(_fresh(made, request.user), status=status.HTTP_201_CREATED)


class ReturnDetailView(_Returns):
    def get(self, request, pk):
        return Response(_fresh(_get(request.user, pk), request.user))

    def put(self, request, pk):
        ret = _get(request.user, pk)
        body = ReturnIn(data=request.data)
        body.is_valid(raise_exception=True)
        values = dict(body.validated_data)
        try:
            returns.save(request.user, ret, lines=_lines(values.pop("lines")), **values)
        except ReturnError as error:
            return _error(error)
        return Response(_fresh(ret, request.user))

    def delete(self, request, pk):
        try:
            returns.delete(request.user, _get(request.user, pk))
        except ReturnError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _text(request, name: str) -> str:
    return str(request.data.get(name, ""))


class _Action(_Returns):
    def _run(self, request, pk, action):
        ret = _get(request.user, pk)
        try:
            action(ret)
        except ReturnError as error:
            return _error(error)
        return Response(_fresh(ret, request.user))


class ConfirmView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda r: returns.confirm(request.user, r, _text(request, "comment"))
        )


class ApproveView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda r: returns.approve(request.user, r, _text(request, "comment"))
        )


class SendBackView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda r: returns.send_back(request.user, r, _text(request, "reason"))
        )


class PdfView(_Returns):
    def get(self, request, pk):
        from django.http import HttpResponse

        from . import return_printing

        ret = _get(request.user, pk)
        response = HttpResponse(return_printing.render(ret), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="return-{ret.number}.pdf"'
        return response
