"""Delivery notes API (P2-04). Rules live in deliveries.py. Sales or the stores (View to
read, Enter to make and issue); only notes of orders the user may see are returned."""

from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess
from apps.inventory import finished
from apps.inventory.models import Item

from . import deliveries, delivery_printing
from .models import DeliveryNote, SalesOrder, SalesOrderLine, TaxInvoice
from .services import SalesError


class _Deliveries(APIView):
    permission_classes = [AreaAccess]
    access_area = "sales"
    access_also_area = "stores"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _get(user, pk) -> DeliveryNote:
    rows = deliveries.visible(user).select_related(
        "order__customer", "order__division", "created_by", "issued_by"
    )
    return get_object_or_404(rows, pk=pk)


def _summary(n: DeliveryNote) -> dict:
    return {
        "id": n.pk,
        "number": n.number,
        "delivery_date": n.delivery_date,
        "status": n.status,
        "status_label": n.get_status_display(),
        "order": {"id": n.order_id, "number": n.order.number, "customer_po": n.order.customer_po},
        "division": n.order.division.code,
        "customer": {"id": n.order.customer_id, "name": n.order.customer.name},
        "vehicle_no": n.vehicle_no,
        "created_by": n.created_by.full_name,
    }


def _order_lines(order: SalesOrder, note: DeliveryNote | None) -> list[dict]:
    """Each line of the order: ordered, delivered by other notes, still to deliver, and the
    quantity on this note."""
    done = deliveries.delivered(order, besides=note)
    here = {} if note is None else {x.order_line_id: x for x in note.lines.select_related("item")}
    rows = []
    for line in order.lines.prefetch_related("schedule"):
        before = done.get(line.pk, 0)
        rows.append(
            {
                "id": line.pk,
                "line_no": line.line_no,
                "description": line.description,
                "drawing_no": line.drawing_no,
                "unit": line.unit,
                "ordered": str(line.quantity),
                "delivered_before": f"{before:.3f}",
                "to_deliver": f"{line.quantity - before:.3f}",
                "quantity": f"{here[line.pk].quantity:.3f}" if line.pk in here else None,
                # P3-16: the finished part leaving stock, and its stock value once issued.
                "item": here[line.pk].item.code
                if line.pk in here and here[line.pk].item_id
                else ("" if line.pk in here else (getattr(finished.part_for(line), "code", ""))),
                "cost": str(here[line.pk].cost) if line.pk in here else "0.00",
                "schedule": [
                    {"due_date": d.due_date, "quantity": str(d.quantity)}
                    for d in line.schedule.all()
                ],
            }
        )
    return rows


def _detail(n: DeliveryNote, user) -> dict:
    body = _summary(n)
    body |= {
        "driver": n.driver,
        "delivery_address": n.delivery_address,
        "notes": n.notes,
        "issued_by": n.issued_by.full_name if n.issued_by else None,
        "issued_at": n.issued_at,
        "received_by": n.received_by,
        "received_on": n.received_on,
        "signed_copy": n.signed_copy_name or None,
        "cancel_reason": n.cancel_reason,
        "invoices": [
            {"id": i.pk, "number": i.number, "status": i.status}
            for i in TaxInvoice.objects.filter(lines__delivery_line__note=n).distinct()
        ],
        "lines": _order_lines(n.order, n),
        "can_edit": deliveries.can_edit(user, n),
        "can_receive": deliveries.can_receive(user, n),
        "can_cancel": deliveries.can_cancel(user, n),
    }
    return body


class LineIn(serializers.Serializer):
    order_line = serializers.IntegerField()
    # Empty for a line that is not on this note (the screen lists every order line).
    quantity = serializers.CharField(max_length=30, allow_blank=True)
    # P3-16: the finished part leaving stock: its code, "" for none; left out, the part of
    # the line's job or production order.
    item = serializers.CharField(max_length=30, allow_blank=True, required=False)


class NoteIn(serializers.Serializer):
    order = serializers.IntegerField(required=False)
    delivery_date = serializers.DateField(required=False)
    vehicle_no = serializers.CharField(max_length=30, allow_blank=True, required=False)
    driver = serializers.CharField(max_length=100, allow_blank=True, required=False)
    delivery_address = serializers.CharField(max_length=1000, allow_blank=True, required=False)
    notes = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    lines = LineIn(many=True)


def _lines(order: SalesOrder, rows) -> list[deliveries.LineInput]:
    by_id = {line.pk: line for line in SalesOrderLine.objects.filter(order=order)}
    result = []
    for row in rows:
        quantity = str(row["quantity"]).strip()
        if quantity in ("", "0"):
            continue  # nothing of this line on the note
        line = by_id.get(row["order_line"])
        if line is None:
            raise SalesError("A line is not on this sales order.")
        item = deliveries.DEFAULT
        if "item" in row:
            code = (row["item"] or "").strip().upper()
            item = Item.objects.filter(code=code).first() if code else None
            if code and item is None:
                raise SalesError(f"Line {line.line_no}: there is no item {code}.")
        result.append(deliveries.LineInput(line, quantity, item))
    return result


def _values(data) -> dict:
    keys = ("delivery_date", "vehicle_no", "driver", "delivery_address", "notes")
    return {k: data[k] for k in keys if k in data}


class DeliveryListView(_Deliveries):
    """Delivery notes, newest first. Filters: status, order."""

    def get(self, request):
        rows = deliveries.visible(request.user).select_related(
            "order__customer", "order__division", "created_by"
        )
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("order", "").isdigit():
            rows = rows.filter(order_id=int(params["order"]))
        return Response([_summary(n) for n in rows[:1000]])

    def post(self, request):
        body = NoteIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        order = get_object_or_404(deliveries.orders_to_deliver(request.user), pk=data.get("order"))
        try:
            note = deliveries.create(
                request.user, order, lines=_lines(order, data["lines"]), **_values(data)
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, note.pk), request.user), status=201)


class OrdersToDeliverView(_Deliveries):
    """The open orders this user may deliver against; with ?order=ID, that order's lines
    and what is still to deliver (for a new note)."""

    def get(self, request):
        rows = deliveries.orders_to_deliver(request.user)
        if request.query_params.get("order", "").isdigit():
            order = get_object_or_404(rows, pk=int(request.query_params["order"]))
            return Response(
                {
                    "id": order.pk,
                    "number": order.number,
                    "customer": order.customer.name,
                    "customer_po": order.customer_po,
                    "delivery_address": order.delivery_address,
                    "lines": _order_lines(order, None),
                }
            )
        return Response(
            [
                {
                    "id": o.pk,
                    "number": o.number,
                    "status": o.status,
                    "division": o.division.code,
                    "customer": o.customer.name,
                    "customer_po": o.customer_po,
                }
                for o in rows.order_by("order_date", "number")[:500]
            ]
        )


class DeliveryDetailView(_Deliveries):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk), request.user))

    def put(self, request, pk):
        note = _get(request.user, pk)
        body = NoteIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            deliveries.save(
                request.user, note, lines=_lines(note.order, data["lines"]), **_values(data)
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))

    def delete(self, request, pk):
        try:
            deliveries.delete(request.user, _get(request.user, pk))
        except SalesError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeliveryIssueView(_Deliveries):
    def post(self, request, pk):
        try:
            deliveries.issue(request.user, _get(request.user, pk))
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))


class ReceiptIn(serializers.Serializer):
    received_by = serializers.CharField(max_length=100)
    received_on = serializers.DateField()
    signed_copy = serializers.FileField(required=False)


class DeliveryReceivedView(_Deliveries):
    def post(self, request, pk):
        body = ReceiptIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            deliveries.record_receipt(
                request.user,
                _get(request.user, pk),
                received_by=data["received_by"],
                received_on=data["received_on"],
                signed_copy=data.get("signed_copy"),
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))


class DeliveryCancelView(_Deliveries):
    def post(self, request, pk):
        try:
            deliveries.cancel(
                request.user, _get(request.user, pk), str(request.data.get("reason", ""))
            )
        except SalesError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))


class DeliveryPdfView(_Deliveries):
    def get(self, request, pk):
        note = _get(request.user, pk)
        response = HttpResponse(delivery_printing.render(note), content_type="application/pdf")
        disposition = "attachment" if request.query_params.get("download") else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="DN-{note.number}.pdf"'
        return response


class SignedCopyView(_Deliveries):
    def get(self, request, pk):
        note = _get(request.user, pk)
        if not note.signed_copy:
            return Response({"detail": "No signed copy."}, status=404)
        return FileResponse(
            note.signed_copy.open("rb"),
            content_type=note.signed_copy_type,
            filename=note.signed_copy_name,
        )
