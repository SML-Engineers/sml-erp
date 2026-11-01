"""Goods receiving notes API (P16-06). Rules live in receipts.py; every endpoint needs Stores
access and shows only the user's divisions. Changes are checked by the service (the stores
person enters; the Director approves through the approval engine)."""

from decimal import Decimal

from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.permissions import AreaAccess

from . import labels, packages, receipts
from .models import GoodsReceipt, GoodsReceiptLine, GoodsReceiptPhoto, ReceiptPackage
from .packages import PackageInput
from .receipts import ReceiptError


class _Receipts(APIView):
    permission_classes = [AreaAccess]
    access_area = "stores"
    access_write_level = "view"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _get(user, pk) -> GoodsReceipt:
    return get_object_or_404(receipts.visible(user), pk=pk)


def _summary(g: GoodsReceipt) -> dict:
    return {
        "id": g.id,
        "number": g.number,
        "receipt_date": g.receipt_date,
        "status": g.status,
        "division": g.division.code,
        "store": g.store.code,
        "purchase_order": {"id": g.purchase_order_id, "label": g.purchase_order.label},
        "supplier": {"id": g.supplier_id, "code": g.supplier.code, "name": g.supplier.name},
        "delivery_note_no": g.delivery_note_no,
        "created_by": g.created_by.full_name,
    }


def _history(kind: str, pk: int) -> list[dict]:
    return [
        {
            "action": row.action,
            "action_label": row.get_action_display(),
            "by": row.user.full_name,
            "at": row.acted_at,
            "reason": row.reason,
        }
        for row in approvals.history(kind, pk)
    ]


def _str(value) -> str | None:
    return None if value is None else str(value)


def _package(p: ReceiptPackage, line: GoodsReceiptLine) -> dict:
    found = packages.check(p, line)
    return {
        "package_no": p.package_no,
        "lot_no": p.lot_no,
        "supplier_lot": p.supplier_lot,
        "gross_weight": _str(p.gross_weight),
        "tare_weight": _str(p.tare_weight),
        "net_weight": _str(p.net_weight),
        "declared_weight": _str(p.declared_weight),
        "pieces": _str(p.pieces),
        "piece_length": _str(p.piece_length),
        "length_mm": _str(p.length_mm),
        "width_mm": _str(p.width_mm),
        "thickness_mm": _str(p.thickness_mm),
        "quantity": _str(p.quantity),
        "damaged": p.damaged,
        "notes": p.notes,
        "check": {
            "basis": found["basis"],
            "expected": _str(found["expected"]),
            "actual": _str(found["actual"]),
            "variance_pct": _str(found["variance_pct"]),
            "outside": found["outside"],
        },
    }


def _line(g: GoodsReceipt, line: GoodsReceiptLine) -> dict:
    item = line.item
    rows = list(line.packages.all())
    draft = g.status == GoodsReceipt.Status.DRAFT
    weighed = [p for p in rows if p.net_weight is not None]
    declared = [p for p in weighed if p.declared_weight is not None]
    return {
        "line_no": line.line_no,
        "po_line": line.po_line_id,
        "item": {
            "id": line.item_id,
            "code": item.code,
            "name": item.name,
            "unit": item.unit,
            "package_type": item.package_type,
            "package_tare": str(item.package_tare),
        },
        "description": line.po_line.description,
        "unit": line.po_line.unit,
        "ordered_quantity": str(line.po_line.quantity),
        "outstanding_quantity": str(
            receipts._outstanding(line.po_line) if draft else line.outstanding_quantity
        ),
        "received_quantity": str(line.received_quantity),
        "damaged_quantity": str(line.damaged_quantity),
        "good_quantity": str(line.good_quantity),
        "excess_quantity": str(line.excess_quantity),
        "notes": line.notes,
        "weight_tolerance_pct": str(
            item.weight_tolerance_pct if draft and not rows else line.weight_tolerance_pct
        ),
        "packages": [_package(p, line) for p in rows],
        "package_totals": {
            "count": len(rows),
            "net_weight": str(sum((p.net_weight for p in weighed), Decimal("0"))),
            "declared_weight": str(sum((p.declared_weight for p in declared), Decimal("0"))),
            "net_of_declared": str(sum((p.net_weight for p in declared), Decimal("0"))),
            "outside": sum(1 for p in rows if packages.check(p, line)["outside"]),
        },
    }


def _detail(g: GoodsReceipt, user) -> dict:
    return _summary(g) | {
        "vehicle_no": g.vehicle_no,
        "supplier_invoice_no": g.supplier_invoice_no,
        "notes": g.notes,
        "confirmed_by": g.confirmed_by.full_name if g.confirmed_by_id else None,
        "confirmed_at": g.confirmed_at,
        "reversal_reason": g.reversal_reason,
        "reversed_at": g.reversed_at,
        "lines": [_line(g, line) for line in g.lines.select_related("item", "po_line")],
        "photos": [
            {
                "id": photo.id,
                "file_name": photo.file_name,
                "content_type": photo.content_type,
                "size": photo.size,
                "uploaded_by": photo.uploaded_by.full_name,
                "uploaded_at": photo.uploaded_at,
            }
            for photo in g.photos.select_related("uploaded_by").order_by("uploaded_at", "id")
        ],
        "can_edit": receipts.can_edit(user, g),
        "can_add_photo": receipts.can_enter(user) and g.status != GoodsReceipt.Status.REVERSED,
        "can_approve_excess": receipts.can_approve_excess(user, g),
        "can_request_reversal": receipts.can_request_reversal(user, g),
        "can_approve_reversal": receipts.can_approve_reversal(user, g),
        "excess_history": _history(receipts.DOC, g.pk),
        "reversal_history": _history(receipts.REVERSAL, g.pk),
    }


def _fresh(g: GoodsReceipt, user) -> dict:
    return _detail(
        GoodsReceipt.objects.select_related(
            "division", "store", "purchase_order", "supplier", "created_by", "confirmed_by"
        ).get(pk=g.pk),
        user,
    )


class LineIn(serializers.Serializer):
    po_line = serializers.IntegerField()
    received_quantity = serializers.CharField(max_length=30)
    damaged_quantity = serializers.CharField(max_length=30, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True)


class ReceiptIn(serializers.Serializer):
    receipt_date = serializers.DateField(required=False)
    delivery_note_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    vehicle_no = serializers.CharField(max_length=30, required=False, allow_blank=True)
    supplier_invoice_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=5000, required=False, allow_blank=True)


class ReceiptChange(ReceiptIn):
    lines = LineIn(many=True)


class ReceivableView(_Receipts):
    """Approved and partly received purchase orders, with what each line still expects."""

    def get(self, request):
        rows = receipts.receivable(request.user).prefetch_related("lines__item")
        return Response(
            [
                {
                    "id": o.id,
                    "label": o.label,
                    "po_date": o.po_date,
                    "delivery_date": o.delivery_date,
                    "status": o.status,
                    "division": o.division.code,
                    "supplier": {
                        "id": o.supplier_id,
                        "code": o.supplier.code,
                        "name": o.supplier.name,
                    },
                    "outstanding_lines": sum(
                        1 for line in o.lines.all() if line.received_quantity < line.quantity
                    ),
                }
                for o in rows.order_by("delivery_date", "number")[:1000]
            ]
        )


class ReceiptListView(_Receipts):
    def get(self, request):
        rows = receipts.visible(request.user).select_related(
            "division", "store", "purchase_order", "supplier", "created_by"
        )
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("purchase_order"):
            rows = rows.filter(purchase_order_id=params["purchase_order"])
        if params.get("waiting") == "me":
            ids = [
                s.document_id
                for kind in (receipts.DOC, receipts.REVERSAL)
                for s in approvals.waiting_for(request.user, kind)
            ]
            rows = rows.filter(pk__in=ids)
        return Response([_summary(g) for g in rows[:2000]])

    def post(self, request):
        body = ReceiptIn(data=request.data)
        body.is_valid(raise_exception=True)
        order = (
            receipts.receivable(request.user).filter(pk=request.data.get("purchase_order")).first()
        )
        if order is None:
            return _error("Choose an approved purchase order.")
        try:
            grn = receipts.create(request.user, order, **body.validated_data)
        except ReceiptError as error:
            return _error(error)
        return Response(_fresh(grn, request.user), status=status.HTTP_201_CREATED)


class ReceiptDetailView(_Receipts):
    def get(self, request, pk):
        return Response(_fresh(_get(request.user, pk), request.user))

    def put(self, request, pk):
        grn = _get(request.user, pk)
        body = ReceiptChange(data=request.data)
        body.is_valid(raise_exception=True)
        values = dict(body.validated_data)
        lines = [
            receipts.LineInput(
                po_line=row["po_line"],
                received=row["received_quantity"],
                damaged=row.get("damaged_quantity") or "0",
                notes=row.get("notes", ""),
            )
            for row in values.pop("lines")
        ]
        try:
            grn = receipts.save(request.user, grn, lines=lines, **values)
        except ReceiptError as error:
            return _error(error)
        return Response(_fresh(grn, request.user))

    def delete(self, request, pk):
        grn = _get(request.user, pk)
        try:
            receipts.delete(request.user, grn)
        except ReceiptError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _text(request, name: str) -> str:
    return str(request.data.get(name, ""))


class _Action(_Receipts):
    def _run(self, request, pk, action):
        grn = _get(request.user, pk)
        try:
            grn = action(grn)
        except ReceiptError as error:
            return _error(error)
        return Response(_fresh(grn, request.user))


class ConfirmView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda g: receipts.confirm(request.user, g, _text(request, "comment"))
        )


class ApproveExcessView(_Action):
    def post(self, request, pk):
        return self._run(
            request,
            pk,
            lambda g: receipts.approve_excess(request.user, g, _text(request, "comment")),
        )


class ReturnView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda g: receipts.send_back(request.user, g, _text(request, "reason"))
        )


class ReverseView(_Action):
    def post(self, request, pk):
        return self._run(
            request,
            pk,
            lambda g: receipts.request_reversal(request.user, g, _text(request, "reason")),
        )


class ApproveReversalView(_Action):
    def post(self, request, pk):
        return self._run(
            request,
            pk,
            lambda g: receipts.approve_reversal(request.user, g, _text(request, "comment")),
        )


class RefuseReversalView(_Action):
    def post(self, request, pk):
        return self._run(
            request,
            pk,
            lambda g: receipts.refuse_reversal(request.user, g, _text(request, "reason")),
        )


class PhotoListView(_Receipts):
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        grn = _get(request.user, pk)
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose a file to add.")
        try:
            receipts.add_photo(request.user, grn, uploaded)
        except ReceiptError as error:
            return _error(error)
        return Response(_fresh(grn, request.user), status=status.HTTP_201_CREATED)


class PhotoDetailView(_Receipts):
    def get(self, request, pk, photo_pk):
        grn = _get(request.user, pk)
        photo = get_object_or_404(GoodsReceiptPhoto, pk=photo_pk, receipt=grn)
        return FileResponse(
            photo.file.open("rb"),
            content_type=photo.content_type,
            filename=photo.file_name,
            as_attachment=request.query_params.get("download") in ("1", "true"),
        )

    def delete(self, request, pk, photo_pk):
        grn = _get(request.user, pk)
        photo = get_object_or_404(GoodsReceiptPhoto, pk=photo_pk, receipt=grn)
        try:
            receipts.remove_photo(request.user, photo)
        except ReceiptError as error:
            return _error(error)
        return Response(_fresh(grn, request.user))


class PackageIn(serializers.Serializer):
    supplier_lot = serializers.CharField(max_length=50, required=False, allow_blank=True)
    gross_weight = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    tare_weight = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    declared_weight = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    pieces = serializers.CharField(max_length=30, required=False, allow_blank=True, allow_null=True)
    piece_length = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    length_mm = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    width_mm = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    thickness_mm = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    damaged = serializers.BooleanField(required=False, default=False)
    notes = serializers.CharField(max_length=200, required=False, allow_blank=True)


class PackagesIn(serializers.Serializer):
    packages = PackageIn(many=True, max_length=packages.MAX_PACKAGES + 1)


class PackagesView(_Receipts):
    """PUT the whole list of packages of one line."""

    def put(self, request, pk, line_no):
        grn = _get(request.user, pk)
        body = PackagesIn(data=request.data)
        body.is_valid(raise_exception=True)
        given = [PackageInput(**row) for row in body.validated_data["packages"]]
        try:
            receipts.set_packages(request.user, grn, line_no, given)
        except ReceiptError as error:
            return _error(error)
        return Response(_fresh(grn, request.user))


class LabelsView(_Receipts):
    def get(self, request, pk):
        grn = _get(request.user, pk)
        line = request.query_params.get("line")
        content = labels.render(grn, int(line) if line and line.isdigit() else None)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="labels-{grn.number}.pdf"'
        return response
