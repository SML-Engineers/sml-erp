"""Purchasing and stores reports, traceability and the dashboard API (P16-13). Rows live in
reports.py; every endpoint needs Purchasing: View and shows only the user's divisions.
?export=xlsx or ?export=pdf gives the same rows as a download."""

from datetime import date

from django.http import Http404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import exports
from apps.core.permissions import AreaAccess
from apps.inventory import receipts as grns

from . import invoices, orders, reports


class _Reports(APIView):
    permission_classes = [AreaAccess]
    access_area = "purchasing"
    access_write_level = "view"


def _day(request, name) -> date | None:
    value = request.query_params.get(name) or ""
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _export(request, rows, *, title, subtitle, columns, filename):
    fmt = (request.query_params.get("export") or "").lower()
    if fmt not in exports.FORMATS:
        return None
    return exports.response(
        fmt,
        title=title,
        subtitle=subtitle,
        columns=columns,
        rows=rows,
        filename=filename,
        user=request.user,
    )


def _as_at(division: str) -> str:
    text = f"As at {timezone.localtime():%d/%m/%Y %H:%M}"
    return text + (f", division {division.upper()}" if division else "")


def _period(request, division: str) -> str:
    start, end = _day(request, "from"), _day(request, "to")
    text = f"{start or 'start'} to {end or 'today'}"
    return text + (f", division {division.upper()}" if division else "")


class OpenOrdersView(_Reports):
    def get(self, request):
        division = request.query_params.get("division", "")
        overdue = request.query_params.get("overdue") in ("1", "true")
        rows = reports.open_orders(request.user, division=division, overdue_only=overdue)
        title = "Overdue deliveries" if overdue else "Open purchase orders"
        return _export(
            request,
            rows,
            title=title,
            subtitle=_as_at(division),
            columns=reports.OPEN_COLUMNS,
            filename="overdue-deliveries" if overdue else "open-purchase-orders",
        ) or Response(rows)


class GrniView(_Reports):
    def get(self, request):
        division = request.query_params.get("division", "")
        rows = reports.grni(
            request.user, division=division, supplier=request.query_params.get("supplier", "")
        )
        return _export(
            request,
            rows,
            title="Goods received not invoiced",
            subtitle=_as_at(division),
            columns=reports.GRNI_COLUMNS,
            filename="grni",
        ) or Response({"rows": rows, "ledger_balance": reports.grni_ledger_balance(division)})


class HeldInvoicesView(_Reports):
    def get(self, request):
        division = request.query_params.get("division", "")
        rows = reports.held_invoices(request.user, division=division)
        return _export(
            request,
            rows,
            title="Supplier invoices held",
            subtitle=_as_at(division),
            columns=reports.HELD_COLUMNS,
            filename="invoices-held",
        ) or Response(rows)


class ExceptionsView(_Reports):
    def get(self, request):
        division = request.query_params.get("division", "")
        rows = reports.exceptions(
            request.user, start=_day(request, "from"), end=_day(request, "to"), division=division
        )
        return _export(
            request,
            rows,
            title="Exceptions approved by the Director",
            subtitle=_period(request, division),
            columns=reports.EXCEPTION_COLUMNS,
            filename="exceptions-approved",
        ) or Response(rows)


class SuppliersView(_Reports):
    def get(self, request):
        division = request.query_params.get("division", "")
        rows = reports.by_supplier(
            request.user, start=_day(request, "from"), end=_day(request, "to"), division=division
        )
        return _export(
            request,
            rows,
            title="Receipts and rejections by supplier",
            subtitle="Goods received " + _period(request, division),
            columns=reports.SUPPLIER_COLUMNS,
            filename="receipts-by-supplier",
        ) or Response(rows)


class TrailView(_Reports):
    """The full trail of a PO, found from the PO, a GRN or a supplier invoice:
    ?po=, ?grn= or ?invoice=."""

    def get(self, request):
        p = request.query_params
        order = None
        if p.get("po"):
            order = orders.visible(request.user).filter(pk=p["po"]).first()
        elif p.get("grn"):
            grn = grns.visible(request.user).filter(pk=p["grn"]).first()
            order = reports.order_of(grn=grn) if grn else None
        elif p.get("invoice"):
            invoice = invoices.visible(request.user).filter(pk=p["invoice"]).first()
            order = reports.order_of(invoice=invoice) if invoice else None
        if order is None or not orders.visible(request.user).filter(pk=order.pk).exists():
            raise Http404
        return Response(reports.trail(request.user, order))


class DashboardView(_Reports):
    def get(self, request):
        return Response(reports.dashboard(request.user, request.query_params.get("division", "")))
