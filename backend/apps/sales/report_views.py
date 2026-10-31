"""Sales reports and the sales dashboard API (P15-11). Rules and rows live in reports.py;
every endpoint needs Sales: View, and shows only what the user may see. ?export=xlsx or
?export=pdf gives the same rows as a download."""

from datetime import date

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import exports
from apps.core.permissions import AreaAccess

from . import reports


class _Reports(APIView):
    permission_classes = [AreaAccess]
    access_area = "sales"
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


def _period(start, end) -> str:
    return f"{start or 'start'} to {end or 'today'}"


def _and_division(division: str) -> str:
    return f", division {division.upper()}" if division else ""


class RegisterView(_Reports):
    """The quotation register: ?from, ?to, ?status, ?customer, ?division, ?salesperson."""

    def get(self, request):
        p = request.query_params
        start, end = _day(request, "from"), _day(request, "to")
        rows = reports.register(
            request.user,
            start=start,
            end=end,
            status=p.get("status", ""),
            customer=p.get("customer", ""),
            division=p.get("division", ""),
            salesperson=p.get("salesperson", ""),
        )
        download = _export(
            request,
            rows,
            title="Quotation register",
            subtitle=f"Quotations dated {_period(start, end)}"
            + _and_division(p.get("division", "")),
            columns=reports.REGISTER_COLUMNS,
            filename="quotation-register",
        )
        return download or Response(
            {
                "rows": rows,
                "summary": reports.register_summary(rows),
                "salespeople": reports.salespeople(request.user),
            }
        )


class WinLossView(_Reports):
    def get(self, request):
        start, end = _day(request, "from"), _day(request, "to")
        division = request.query_params.get("division", "")
        rows = reports.win_loss(request.user, start=start, end=end, division=division)
        download = _export(
            request,
            rows,
            title="Quotations won and lost",
            subtitle=f"Decided {_period(start, end)}" + _and_division(division),
            columns=reports.WIN_LOSS_COLUMNS,
            filename="win-loss",
        )
        return download or Response({"rows": rows, "summary": reports.win_loss_summary(rows)})


class AttentionView(_Reports):
    def get(self, request):
        division = request.query_params.get("division", "")
        rows = reports.attention(request.user, division=division)
        download = _export(
            request,
            rows,
            title="Quotations needing attention",
            subtitle=f"Awaiting approval, or expiring within {reports.EXPIRY_DAYS} days, "
            f"as at {timezone.localtime():%d/%m/%Y %H:%M}" + _and_division(division),
            columns=reports.ATTENTION_COLUMNS,
            filename="quotations-attention",
        )
        return download or Response(rows)


class OpenOrdersView(_Reports):
    def get(self, request):
        p = request.query_params
        until = _day(request, "until")
        rows = reports.open_orders(
            request.user,
            division=p.get("division", ""),
            customer=p.get("customer", ""),
            until=until,
        )
        download = _export(
            request,
            rows,
            title="Open sales orders: deliveries",
            subtitle=f"Deliveries still to make{f' up to {until}' if until else ''}, "
            f"as at {timezone.localdate():%d/%m/%Y}" + _and_division(p.get("division", "")),
            columns=reports.ORDER_COLUMNS,
            filename="open-sales-orders",
        )
        return download or Response(rows)


class AdvancesOpenView(_Reports):
    def get(self, request):
        p = request.query_params
        rows = reports.advances_open(
            request.user, division=p.get("division", ""), customer=p.get("customer", "")
        )
        download = _export(
            request,
            rows,
            title="Customer advances not yet set off",
            subtitle=f"As at {timezone.localdate():%d/%m/%Y}"
            + _and_division(p.get("division", "")),
            columns=reports.ADVANCE_COLUMNS,
            filename="advances-not-set-off",
        )
        return download or Response(rows)


class DashboardView(_Reports):
    """The sales tiles on the home page; ?division=IM for one division."""

    def get(self, request):
        return Response(reports.dashboard(request.user, request.query_params.get("division", "")))
