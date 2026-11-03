"""Sales orders API (P15-10). Rules live in orders.py; every endpoint checks Sales access and
returns only orders the user may see."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounting.models import TaxCode
from apps.core import approvals
from apps.core.models import Division
from apps.core.permissions import AreaAccess
from apps.masters.models import Customer, CustomerContact

from . import deliveries, invoices, orders, proformas
from .models import QuotationLine, SalesOrder
from .services import SalesError
from .services import visible as visible_quotations


class _Sales(APIView):
    permission_classes = [AreaAccess]
    access_area = "sales"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _get(user, pk) -> SalesOrder:
    return get_object_or_404(orders.visible(user), pk=pk)


def _summary(o: SalesOrder) -> dict:
    return {
        "id": o.id,
        "number": o.number,
        "order_date": o.order_date,
        "status": o.status,
        "source": o.source,
        "division": o.division.code,
        "customer": {"id": o.customer_id, "code": o.customer.code, "name": o.customer.name},
        "customer_po": o.customer_po,
        "currency": o.currency.code,
        "total_amount": str(o.total_amount),
        "total_lkr": str(o.total_lkr),
        # The first delivery date of an open order (its delivery dates, for the reports).
        "next_delivery": min(
            (d.due_date for line in o.lines.all() for d in line.schedule.all()),
            default=None,
        )
        if o.status in (SalesOrder.Status.OPEN, SalesOrder.Status.PARTLY_DELIVERED)
        else None,
        "created_by": o.created_by.full_name,
    }


def _detail(o: SalesOrder, user) -> dict:
    body = _summary(o)
    state = approvals.state_of(orders.DOC, o.pk)
    done = deliveries.delivered(o)
    body |= {
        "quotation": None
        if o.quotation_id is None
        else {"id": o.quotation_id, "label": o.quotation.label},
        "proforma": None
        if o.proforma_id is None
        else {"id": o.proforma_id, "number": o.proforma.number},
        "contact": None if o.contact is None else {"id": o.contact_id, "name": o.contact.name},
        "po_date": o.po_date,
        "exchange_rate": str(o.exchange_rate),
        "payment_terms": o.payment_terms,
        "incoterm": o.incoterm,
        "delivery_address": o.delivery_address,
        "notes": o.notes,
        "discount_pct": str(o.discount_pct),
        "discount_total": str(o.discount_total),
        "subtotal": str(o.subtotal),
        "tax_total": str(o.tax_total),
        "cancel_reason": o.cancel_reason,
        "confirmed_at": o.confirmed_at,
        "lines": [
            {
                "line_no": line.line_no,
                "quotation_line": line.quotation_line_id,
                "description": line.description,
                "drawing_no": line.drawing_no,
                "quantity": str(line.quantity),
                "unit": line.unit,
                "unit_price": str(line.unit_price),
                "tax_code": line.tax_code.code if line.tax_code else None,
                "is_tooling": line.is_tooling,
                "amount": str(line.amount),
                "discount": str(line.discount),
                "tax_amount": str(line.tax_amount),
                "total": str(line.total),
                "delivered": f"{done.get(line.pk, 0):.3f}",
                "schedule": [
                    {"due_date": d.due_date, "quantity": str(d.quantity)}
                    for d in line.schedule.all()
                ],
            }
            for line in o.lines.select_related("tax_code").prefetch_related("schedule")
        ],
        "quotation_lines": []
        if o.quotation_id is None
        else [
            {
                "id": q.id,
                "line_no": q.line_no,
                "description": q.description,
                "quantity": str(q.quantity),
            }
            for q in o.quotation.lines.all()
        ],
        "deliveries": [
            {
                "id": n.pk,
                "number": n.number,
                "delivery_date": n.delivery_date,
                "status": n.status,
                "status_label": n.get_status_display(),
            }
            for n in o.deliveries.order_by("delivery_date", "number")
        ],
        "can_deliver": deliveries.orders_to_deliver(user).filter(pk=o.pk).exists(),
        "invoices": [
            {
                "id": i.pk,
                "number": i.number,
                "status": i.status,
                "invoice_date": i.invoice_date,
                "total_amount": f"{i.total_amount:.2f}",
            }
            for i in o.invoices.order_by("invoice_date", "id")
        ],
        "can_invoice": invoices.orders_to_invoice(user).filter(pk=o.pk).exists(),
        "can_edit": orders.can_edit(user, o),
        "can_approve": orders.can_approve(user, o),
        "can_complete": orders.can_complete(user, o),
        "can_cancel": orders.can_cancel(user, o),
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
        "advances": [
            {"id": a.id, "number": a.number, "status": a.status, "amount": str(a.amount)}
            for a in o.advances.all()
        ],
    }
    return body


class DeliveryInput(serializers.Serializer):
    due_date = serializers.DateField()
    quantity = serializers.CharField(max_length=30)


class OrderLineInput(serializers.Serializer):
    quantity = serializers.CharField(max_length=30)
    quotation_line = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True)
    unit_price = serializers.CharField(max_length=30, required=False, allow_blank=True)
    unit = serializers.CharField(max_length=20, required=False, allow_blank=True)
    drawing_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    tax_code = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    schedule = DeliveryInput(many=True)


class OrderInput(serializers.Serializer):
    customer_po = serializers.CharField(max_length=50, required=False, allow_blank=True)
    po_date = serializers.DateField(required=False, allow_null=True)
    contact = serializers.IntegerField(required=False, allow_null=True)
    payment_terms = serializers.CharField(max_length=200, required=False, allow_blank=True)
    incoterm = serializers.CharField(max_length=3, required=False, allow_blank=True)
    delivery_address = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    discount_pct = serializers.CharField(max_length=10, required=False, allow_blank=True)
    lines = OrderLineInput(many=True)


def _lines(rows) -> list[orders.LineInput]:
    result = []
    for n, row in enumerate(rows, start=1):
        source = None
        if row.get("quotation_line"):
            source = (
                QuotationLine.objects.prefetch_related("breaks")
                .filter(pk=row["quotation_line"])
                .first()
            )
        tax_code = None
        code = (row.get("tax_code") or "").strip().upper()
        if code:
            tax_code = TaxCode.objects.filter(code=code).first()
            if tax_code is None:
                raise SalesError(f"Line {n}: there is no tax code {code}.")
        result.append(
            orders.LineInput(
                quantity=row["quantity"],
                quotation_line=source,
                description=row.get("description", ""),
                unit_price=row.get("unit_price"),
                unit=row.get("unit") or "pcs",
                drawing_no=row.get("drawing_no", ""),
                tax_code=tax_code,
                schedule=[orders.Delivery(d["due_date"], d["quantity"]) for d in row["schedule"]],
            )
        )
    return result


def _values(data: dict) -> dict:
    values = {k: v for k, v in data.items() if k not in ("lines", "contact")}
    if "contact" in data:
        values["contact"] = (
            None
            if data["contact"] is None
            else CustomerContact.objects.filter(pk=data["contact"]).first() or "unknown"
        )
    return values


class SalesOrderListView(_Sales):
    def get(self, request):
        rows = (
            orders.visible(request.user)
            .select_related("division", "customer", "currency", "created_by")
            .prefetch_related("lines__schedule")
        )
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("waiting") == "me":
            waiting = approvals.waiting_for(request.user, orders.DOC)
            rows = rows.filter(pk__in=[state.document_id for state in waiting])
        return Response([_summary(o) for o in rows[:2000]])

    def post(self, request):
        data = request.data
        try:
            if data.get("quotation"):
                quotation = visible_quotations(request.user).filter(pk=data["quotation"]).first()
                if quotation is None:
                    return _error("Choose one of your accepted quotations.")
                order = orders.from_quotation(request.user, quotation)
            elif data.get("proforma"):
                proforma = proformas.visible(request.user).filter(pk=data["proforma"]).first()
                if proforma is None:
                    return _error("Choose one of your issued proformas.")
                order = orders.from_proforma(request.user, proforma)
            else:
                body = OrderInput(data=data)
                body.is_valid(raise_exception=True)
                division = Division.objects.filter(
                    code=str(data.get("division", "")).upper()
                ).first()
                customer = Customer.objects.filter(pk=data.get("customer")).first()
                order = orders.direct(
                    request.user,
                    customer=customer,
                    division=division,
                    lines=_lines(body.validated_data["lines"]),
                    **_values(body.validated_data),
                )
        except SalesError as error:
            return _error(error)
        return Response(_detail(order, request.user), status=status.HTTP_201_CREATED)


class SalesOrderDetailView(_Sales):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk), request.user))

    def put(self, request, pk):
        order = _get(request.user, pk)
        body = OrderInput(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            order = orders.save(
                request.user,
                order,
                lines=_lines(body.validated_data["lines"]),
                **_values(body.validated_data),
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(SalesOrder.objects.get(pk=order.pk), request.user))


class _Action(_Sales):
    def _run(self, request, pk, action):
        order = _get(request.user, pk)
        try:
            order = action(order)
        except SalesError as error:
            return _error(error)
        return Response(_detail(SalesOrder.objects.get(pk=order.pk), request.user))


class SalesOrderConfirmView(_Action):
    def post(self, request, pk):
        comment = str(request.data.get("comment", ""))
        return self._run(request, pk, lambda o: orders.confirm(request.user, o, comment))


class SalesOrderApproveView(_Action):
    access_write_level = "approve"

    def post(self, request, pk):
        comment = str(request.data.get("comment", ""))
        return self._run(request, pk, lambda o: orders.approve(request.user, o, comment))


class SalesOrderReturnView(_Action):
    access_write_level = "approve"

    def post(self, request, pk):
        reason = str(request.data.get("reason", ""))
        return self._run(request, pk, lambda o: orders.send_back(request.user, o, reason))


class SalesOrderCompleteView(_Action):
    # The creator (Sales: Enter) or the Sales Manager (Sales: Approve); the service decides.
    access_write_level = "view"

    def post(self, request, pk):
        return self._run(request, pk, lambda o: orders.complete(request.user, o))


class SalesOrderCancelView(_Action):
    access_write_level = "view"

    def post(self, request, pk):
        reason = str(request.data.get("reason", ""))
        return self._run(request, pk, lambda o: orders.cancel(request.user, o, reason))
