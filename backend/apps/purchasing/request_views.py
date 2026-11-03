"""Reorder levels and purchase requests API (P2-13). Rules live in requests.py. The stores
person or purchasing raises; the approver decides; purchasing makes the order."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.models import Division
from apps.core.permissions import AreaAccess
from apps.inventory.models import Item, Store
from apps.masters.models import Supplier

from . import requests as service
from .models import PurchaseRequest
from .orders import PurchasingError


class _Requests(APIView):
    permission_classes = [AreaAccess]
    access_area = "purchasing"
    access_also_area = "stores"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _qty(value) -> str:
    return f"{value:.3f}"


def _supplier(s: Supplier | None) -> dict | None:
    return None if s is None else {"id": s.pk, "code": s.code, "name": s.name}


# --- Reorder levels ---------------------------------------------------------------------


def _level(p: service.Position) -> dict:
    row = p.row
    supplier = service.usual_supplier(row)
    return {
        "id": row.pk,
        "item": {"id": row.item_id, "code": row.item.code, "name": row.item.name},
        "unit": row.item.unit,
        "store": {"id": row.store_id, "code": row.store.code, "name": row.store.name},
        "division": row.store.division.code,
        "level": _qty(row.level),
        "quantity": _qty(row.quantity),
        "usual_supplier": _supplier(row.usual_supplier),
        "suggested_supplier": _supplier(supplier),
        "on_hand": _qty(p.on_hand),
        "on_order": _qty(p.on_order),
        "requested": _qty(p.requested),
        "low": p.low,
        "alerted_at": row.alerted_at,
    }


class LevelIn(serializers.Serializer):
    item = serializers.IntegerField()
    store = serializers.IntegerField()
    level = serializers.CharField(max_length=30)
    quantity = serializers.CharField(max_length=30)
    usual_supplier = serializers.IntegerField(required=False, allow_null=True)


class LevelListView(_Requests):
    """GET: every level of my divisions with its stock (?low=1: only those at or below)."""

    def get(self, request):
        rows = service.positions(service.levels(request.user))
        if request.query_params.get("low"):
            rows = [p for p in rows if p.low]
        return Response([_level(p) for p in rows])

    def post(self, request):
        body = LevelIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        supplier = None
        if data.get("usual_supplier"):
            supplier = Supplier.objects.filter(pk=data["usual_supplier"]).first()
        try:
            row = service.set_level(
                request.user,
                item=Item.objects.filter(pk=data["item"]).first(),
                store=Store.objects.select_related("division").filter(pk=data["store"]).first(),
                level=data["level"],
                quantity=data["quantity"],
                usual_supplier=supplier,
            )
        except PurchasingError as error:
            return _error(error)
        return Response(_level(service.positions([row])[0]), status=status.HTTP_201_CREATED)


class LevelDetailView(_Requests):
    def delete(self, request, pk):
        row = get_object_or_404(service.levels(request.user), pk=pk)
        try:
            service.remove_level(request.user, row)
        except PurchasingError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LevelRequestView(_Requests):
    """One click: a draft purchase request for the reorder quantity."""

    def post(self, request, pk):
        row = get_object_or_404(service.levels(request.user), pk=pk)
        try:
            made = service.from_level(request.user, row)
        except PurchasingError as error:
            return _error(error)
        return Response(_detail(made, request.user), status=status.HTTP_201_CREATED)


# --- Purchase requests ------------------------------------------------------------------


def _summary(r: PurchaseRequest) -> dict:
    return {
        "id": r.pk,
        "number": r.number,
        "status": r.status,
        "division": r.division.code,
        "store": None if r.store_id is None else r.store.code,
        "supplier": _supplier(r.supplier),
        "needed_by": r.needed_by,
        "from_reorder": r.from_reorder,
        "created_by": r.created_by.full_name,
        "created_at": r.created_at,
        "purchase_order": None
        if r.purchase_order_id is None
        else {"id": r.purchase_order_id, "label": r.purchase_order.label},
    }


def _detail(r: PurchaseRequest, user) -> dict:
    lines = list(r.lines.select_related("item"))
    supplier = r.supplier
    return _summary(r) | {
        "reason": r.reason,
        "end_reason": r.end_reason,
        "approved_at": r.approved_at,
        "lines": [
            {
                "line_no": line.line_no,
                "item": {"id": line.item_id, "code": line.item.code, "name": line.item.name},
                "unit": line.item.unit,
                "quantity": _qty(line.quantity),
                "notes": line.notes,
                # The last price paid to the supplier, used when the order is made.
                "last_price": None
                if supplier is None or (last := service.last_line(line.item, supplier)) is None
                else str(last.unit_price),
            }
            for line in lines
        ],
        "approvals": [
            {
                "level": row.level,
                "action": row.action,
                "user": row.user.full_name,
                "reason": row.reason,
                "acted_at": row.acted_at,
            }
            for row in approvals.history(service.DOC, r.pk)
        ],
        "can_edit": service.can_edit(user, r),
        "can_approve": service.can_approve(user, r),
        "can_order": service.can_order(user, r),
        "can_cancel": service.can_cancel(user, r),
    }


def _get(user, pk) -> PurchaseRequest:
    rows = service.visible(user).select_related(
        "division", "store", "supplier", "created_by", "purchase_order"
    )
    return get_object_or_404(rows, pk=pk)


class LineIn(serializers.Serializer):
    item = serializers.IntegerField()
    quantity = serializers.CharField(max_length=30)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class RequestIn(serializers.Serializer):
    supplier = serializers.IntegerField(required=False, allow_null=True)
    needed_by = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    lines = LineIn(many=True)


def _input(data: dict) -> tuple[list, dict]:
    lines = [
        service.LineInput(
            item=Item.objects.select_related("division").filter(pk=row["item"]).first(),
            quantity=row["quantity"],
            notes=row.get("notes", ""),
        )
        for row in data["lines"]
    ]
    values = {"reason": data.get("reason", "")}
    if "needed_by" in data:
        values["needed_by"] = data["needed_by"]
    if "supplier" in data:
        values["supplier"] = (
            Supplier.objects.filter(pk=data["supplier"]).first() if data["supplier"] else None
        )
    return lines, values


class RequestListView(_Requests):
    def get(self, request):
        rows = service.visible(request.user).select_related(
            "division", "store", "supplier", "created_by", "purchase_order"
        )
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("waiting") == "me":
            waiting = approvals.waiting_for(request.user, service.DOC)
            rows = rows.filter(pk__in=[s.document_id for s in waiting])
        return Response([_summary(r) for r in rows[:2000]])

    def post(self, request):
        body = RequestIn(data=request.data)
        body.is_valid(raise_exception=True)
        lines, values = _input(body.validated_data)
        store = None
        if request.data.get("store"):
            stores = Store.objects.select_related("division")
            store = stores.filter(pk=request.data["store"]).first()
        try:
            made = service.create(
                request.user,
                division=Division.objects.filter(
                    code=str(request.data.get("division", "")).upper()
                ).first(),
                store=store,
                lines=lines,
                **values,
            )
        except PurchasingError as error:
            return _error(error)
        return Response(_detail(made, request.user), status=status.HTTP_201_CREATED)


class RequestDetailView(_Requests):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk), request.user))

    def patch(self, request, pk):
        found = _get(request.user, pk)
        body = RequestIn(data=request.data)
        body.is_valid(raise_exception=True)
        lines, values = _input(body.validated_data)
        try:
            service.save(request.user, found, lines=lines, **values)
        except PurchasingError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))


def _text(request, name: str) -> str:
    return str(request.data.get(name) or "")


class RequestActionView(_Requests):
    action = "submit"

    def get_permissions(self):
        # The approver decides; the service checks they are the one waited for.
        if self.action in ("approve", "return", "reject"):
            self.access_write_level = "view"
        return super().get_permissions()

    def post(self, request, pk):
        found = _get(request.user, pk)
        try:
            if self.action == "submit":
                service.submit(request.user, found, _text(request, "comment"))
            elif self.action == "approve":
                service.approve(request.user, found, _text(request, "comment"))
            elif self.action == "return":
                service.send_back(request.user, found, _text(request, "reason"))
            elif self.action == "reject":
                service.reject(request.user, found, _text(request, "reason"))
            elif self.action == "cancel":
                service.cancel(request.user, found, _text(request, "reason"))
            elif self.action == "order":
                supplier = None
                if request.data.get("supplier"):
                    supplier = Supplier.objects.filter(pk=request.data["supplier"]).first()
                    if supplier is None:
                        raise PurchasingError("Unknown supplier.")
                order = service.make_order(
                    request.user,
                    found,
                    supplier=supplier,
                    prices={str(k): v for k, v in (request.data.get("prices") or {}).items()},
                )
                body = _detail(_get(request.user, pk), request.user)
                body["purchase_order"] = {"id": order.pk, "label": order.label}
                return Response(body)
        except PurchasingError as error:
            return _error(error)
        return Response(_detail(_get(request.user, pk), request.user))
