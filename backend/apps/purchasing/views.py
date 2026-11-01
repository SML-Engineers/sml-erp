"""Purchase orders API (P16-04). Rules live in orders.py; every endpoint needs Purchasing
access and shows only the user's divisions."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounting.models import TaxCode
from apps.core import approvals
from apps.core.models import Division
from apps.core.permissions import AreaAccess
from apps.inventory.models import Item
from apps.masters.models import Supplier

from . import orders
from .models import PurchaseOrder
from .orders import PurchasingError


class _Purchasing(APIView):
    permission_classes = [AreaAccess]
    access_area = "purchasing"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _get(user, pk) -> PurchaseOrder:
    return get_object_or_404(orders.visible(user), pk=pk)


def _summary(o: PurchaseOrder) -> dict:
    return {
        "id": o.id,
        "number": o.number,
        "revision": o.revision,
        "label": o.label,
        "po_date": o.po_date,
        "delivery_date": o.delivery_date,
        "status": o.status,
        "division": o.division.code,
        "supplier": {"id": o.supplier_id, "code": o.supplier.code, "name": o.supplier.name},
        "currency": o.currency.code,
        "total_amount": str(o.total_amount),
        "total_lkr": str(o.total_lkr),
        "created_by": o.created_by.full_name,
    }


def _detail(o: PurchaseOrder, user) -> dict:
    state = approvals.state_of(orders.DOC, o.pk)
    return _summary(o) | {
        "deliver_to": o.deliver_to,
        "pay_mode": o.pay_mode,
        "payment_terms": o.payment_terms,
        "exchange_rate": str(o.exchange_rate),
        "notes": o.notes,
        "subtotal": str(o.subtotal),
        "tax_total": str(o.tax_total),
        "approved_at": o.approved_at,
        "end_reason": o.end_reason,
        "parent": None if o.parent_id is None else {"id": o.parent_id, "label": o.parent.label},
        "revisions": [
            {"id": r.id, "label": r.label, "status": r.status} for r in o.revisions.all()
        ],
        "lines": [
            {
                "line_no": line.line_no,
                "item": {"id": line.item_id, "code": line.item.code},
                "description": line.description,
                "unit": line.unit,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "amount": str(line.amount),
                "tax_code": line.tax_code.code if line.tax_code else None,
                "tax_amount": str(line.tax_amount),
                "total": str(line.total),
                "received_quantity": str(line.received_quantity),
            }
            for line in o.lines.select_related("item", "tax_code")
        ],
        "can_edit": orders.can_edit(user, o),
        "can_approve": orders.can_approve(user, o),
        "can_revise": orders.can_revise(user, o),
        "can_cancel": orders.can_cancel(user, o),
        "can_close": orders.can_close(user, o),
        "approval": None
        if state is None
        else {
            "status": state.status,
            "history": [
                {
                    "action": row.action,
                    "action_label": row.get_action_display(),
                    "by": row.user.full_name,
                    "at": row.acted_at,
                    "reason": row.reason,
                }
                for row in approvals.history(orders.DOC, o.pk)
            ],
        },
    }


class LineIn(serializers.Serializer):
    item = serializers.IntegerField()
    quantity = serializers.CharField(max_length=30)
    unit_price = serializers.CharField(max_length=30)
    tax_code = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)


class OrderIn(serializers.Serializer):
    delivery_date = serializers.DateField(required=False, allow_null=True)
    deliver_to = serializers.CharField(required=False, allow_blank=True)
    pay_mode = serializers.CharField(max_length=10, required=False)
    payment_terms = serializers.CharField(max_length=100, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    lines = LineIn(many=True)


def _lines(rows) -> list[orders.LineInput]:
    result = []
    for n, row in enumerate(rows, start=1):
        code = (row.get("tax_code") or "").strip().upper()
        tax = None
        if code:
            tax = TaxCode.objects.filter(code=code).first()
            if tax is None:
                raise PurchasingError(f"Line {n}: there is no tax code {code}.")
        result.append(
            orders.LineInput(
                item=Item.objects.select_related("division").filter(pk=row["item"]).first(),
                quantity=row["quantity"],
                unit_price=row["unit_price"],
                tax_code=tax,
                description=row.get("description", ""),
            )
        )
    return result


def _values(data: dict) -> dict:
    return {k: v for k, v in data.items() if k != "lines"}


class OrderListView(_Purchasing):
    def get(self, request):
        rows = orders.visible(request.user).select_related(
            "division", "supplier", "currency", "created_by"
        )
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("waiting") == "me":
            waiting = approvals.waiting_for(request.user, orders.DOC)
            rows = rows.filter(pk__in=[s.document_id for s in waiting])
        return Response([_summary(o) for o in rows[:2000]])

    def post(self, request):
        body = OrderIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            order = orders.create(
                request.user,
                supplier=Supplier.objects.filter(pk=request.data.get("supplier")).first(),
                division=Division.objects.filter(
                    code=str(request.data.get("division", "")).upper()
                ).first(),
                lines=_lines(body.validated_data["lines"]),
                **_values(body.validated_data),
            )
        except PurchasingError as error:
            return _error(error)
        return Response(_detail(order, request.user), status=status.HTTP_201_CREATED)


class OrderDetailView(_Purchasing):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk), request.user))

    def put(self, request, pk):
        order = _get(request.user, pk)
        body = OrderIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            order = orders.save(
                request.user,
                order,
                lines=_lines(body.validated_data["lines"]),
                **_values(body.validated_data),
            )
        except PurchasingError as error:
            return _error(error)
        return Response(_detail(PurchaseOrder.objects.get(pk=order.pk), request.user))


class _Action(_Purchasing):
    def _run(self, request, pk, action):
        order = _get(request.user, pk)
        try:
            order = action(order)
        except PurchasingError as error:
            return _error(error)
        return Response(_detail(PurchaseOrder.objects.get(pk=order.pk), request.user))


def _text(request, name: str) -> str:
    return str(request.data.get(name, ""))


class SubmitView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda o: orders.submit(request.user, o, _text(request, "comment"))
        )


class ApproveView(_Action):
    access_write_level = "approve"

    def post(self, request, pk):
        return self._run(
            request, pk, lambda o: orders.approve(request.user, o, _text(request, "comment"))
        )


class ReturnView(_Action):
    access_write_level = "approve"

    def post(self, request, pk):
        return self._run(
            request, pk, lambda o: orders.send_back(request.user, o, _text(request, "reason"))
        )


class ReviseView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda o: orders.revise(request.user, o, _text(request, "reason"))
        )


class CancelView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda o: orders.cancel(request.user, o, _text(request, "reason"))
        )


class CloseView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda o: orders.close(request.user, o, _text(request, "reason"))
        )
