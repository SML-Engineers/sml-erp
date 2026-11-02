"""Stock on hand and stock movements (P16-09). Balances are worked out from the movements;
Stores: View, for the user's divisions."""

from decimal import Decimal

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import exports
from apps.core.access import division_scope
from apps.core.permissions import AreaAccess

from . import stock
from .models import Item, StockMovement, Store


class _Stock(APIView):
    permission_classes = [AreaAccess]
    access_area = "stores"


def _movements(request):
    rows = StockMovement.objects.filter(division__in=division_scope(request.user))
    params = request.query_params
    if params.get("division"):
        rows = rows.filter(division__code=params["division"].upper())
    if params.get("item"):
        rows = rows.filter(item_id=params["item"])
    if params.get("store"):
        rows = rows.filter(store_id=params["store"])
    if params.get("lot"):
        rows = rows.filter(lot_no=params["lot"].strip())
    return rows


class StockOnHandView(_Stock):
    def get(self, request):
        rows = _movements(request)
        by_lot = request.query_params.get("lots") in ("1", "true")
        found = stock.balances(rows, by_lot=by_lot)
        averages = stock.average_costs(rows)
        items = Item.objects.in_bulk({r["item"] for r in found})
        stores = Store.objects.select_related("division").in_bulk({r["store"] for r in found})
        total = sum((r["value"] for r in found), Decimal("0"))
        fmt = (request.query_params.get("export") or "").lower()
        if fmt in exports.FORMATS:
            rows = [
                {
                    "item": f"{items[r['item']].code} {items[r['item']].name}",
                    "store": stores[r["store"]].code,
                    "lot": r.get("lot_no") or "",
                    "quantity": f"{r['quantity'].normalize():f}",
                    "unit": items[r["item"]].unit,
                    "average_cost": f"{averages[r['item']]:,.2f}"
                    if stores[r["store"]].kind == Store.Kind.MAIN and r["item"] in averages
                    else "",
                    "value": r["value"],
                }
                for r in found
            ]
            columns = [
                exports.Column("item", "Item", width=2.2),
                exports.Column("store", "Store", width=0.8),
                *([exports.Column("lot", "Lot", width=1.4)] if by_lot else []),
                exports.Column("quantity", "Quantity", "number", width=0.8),
                exports.Column("unit", "Unit", width=0.5),
                exports.Column("average_cost", "Average cost (LKR)", "number", width=0.9),
                exports.Column("value", "Value (LKR)", "money"),
            ]
            return exports.response(
                fmt,
                title="Stock on hand",
                subtitle=f"As at {timezone.localtime():%d/%m/%Y %H:%M}"
                + (" by lot" if by_lot else ""),
                columns=columns,
                rows=rows,
                filename="stock-on-hand",
                user=request.user,
            )
        return Response(
            {
                "total_value": str(total),
                "rows": [
                    {
                        "item": {
                            "id": r["item"],
                            "code": items[r["item"]].code,
                            "name": items[r["item"]].name,
                            "unit": items[r["item"]].unit,
                        },
                        "store": {
                            "id": r["store"],
                            "code": stores[r["store"]].code,
                            "kind": stores[r["store"]].kind,
                            "division": stores[r["store"]].division.code,
                        },
                        "lot_no": r.get("lot_no"),
                        "quantity": str(r["quantity"]),
                        "value": str(r["value"]),
                        "average_cost": None
                        if stores[r["store"]].kind != Store.Kind.MAIN
                        else str(averages.get(r["item"], "")) or None,
                    }
                    for r in found
                ],
            }
        )


class MovementListView(_Stock):
    def get(self, request):
        rows = (
            _movements(request)
            .select_related(
                "item",
                "store",
                "receipt_line__receipt",
                "opening_line__opening",
                "journal_entry",
                "created_by",
            )
            .order_by("-movement_date", "-id")[:2000]
        )
        return Response(
            [
                {
                    "id": m.id,
                    "date": m.movement_date,
                    "kind": m.kind,
                    "item": {"id": m.item_id, "code": m.item.code, "unit": m.item.unit},
                    "store": m.store.code,
                    "lot_no": m.lot_no,
                    "quantity": str(m.quantity),
                    "value": str(m.value),
                    "grn": None
                    if m.receipt_line_id is None
                    else {"id": m.receipt_line.receipt_id, "number": m.receipt_line.receipt.number},
                    "opening": None
                    if m.opening_line_id is None
                    else {
                        "id": m.opening_line.opening_id,
                        "number": m.opening_line.opening.number,
                    },
                    "journal": None if m.journal_entry_id is None else m.journal_entry.number,
                    "by": m.created_by.full_name,
                }
                for m in rows
            ]
        )
