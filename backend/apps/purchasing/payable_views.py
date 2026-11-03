"""Payables aging and supplier statements API (P2-10). Rules live in payables.py. Vouchers or
Accounting: View to read, Enter to type in or import a statement; marking it checked is the
Accountant's (the service checks)."""

from datetime import date

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import exports
from apps.core.exports import Column
from apps.core.models import Division
from apps.core.permissions import AreaAccess
from apps.masters.models import Supplier

from . import payables
from .models import SupplierStatement
from .orders import PurchasingError


class _Payables(APIView):
    permission_classes = [AreaAccess]
    access_area = "vouchers"
    access_also_area = "accounting"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _day(request, name: str, default: date) -> date:
    value = request.query_params.get(name) or ""
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        return default


def _money(value) -> str:
    return f"{value:.2f}"


AGING_COLUMNS = [
    Column("code", "Code", width=0.8),
    Column("supplier", "Supplier", width=2.4),
    *[Column(key, label, "money") for key, label in payables.BUCKETS],
    Column("total", "Total owed", "money"),
]


class AgingView(_Payables):
    """?as_at, ?supplier=id, ?division=WS, ?export=xlsx|pdf."""

    access_write_level = "view"

    def get(self, request):
        p = request.query_params
        as_at = _day(request, "as_at", timezone.localdate())
        supplier = Supplier.objects.filter(pk=p["supplier"]).first() if p.get("supplier") else None
        division = (
            Division.objects.filter(code=p["division"].upper()).first()
            if p.get("division")
            else None
        )
        rows = payables.aging(request.user, as_at, supplier=supplier, division=division)
        fmt = (p.get("export") or "").lower()
        if fmt in exports.FORMATS:
            return exports.response(
                fmt,
                title="Payables aging",
                subtitle=f"What we owe suppliers as at {as_at:%d/%m/%Y}, by days past the due "
                "date" + (f", division {division.code}" if division else ""),
                columns=AGING_COLUMNS,
                rows=rows,
                filename=f"payables-aging-{as_at:%Y-%m-%d}",
                user=request.user,
            )
        items = []
        if supplier is not None:
            items = [
                {
                    "kind": i["kind"],
                    "reference": i["reference"],
                    "document": i["document"],
                    "link": i["link"],
                    "division": i["division"].code,
                    "date": i["date"],
                    "due_date": i["due_date"],
                    "days_overdue": max(i["days_overdue"], 0),
                    "total": _money(i["total"]),
                    "open": _money(i["open"]),
                }
                for i in payables.open_items(
                    as_at, user=request.user, supplier=supplier, division=division
                )
            ]
        return Response({"as_at": as_at, "rows": rows, "items": items})


class LineIn(serializers.Serializer):
    date = serializers.CharField(max_length=30)
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    debit = serializers.CharField(max_length=30, required=False, allow_blank=True)
    credit = serializers.CharField(max_length=30, required=False, allow_blank=True)


class StatementIn(serializers.Serializer):
    supplier = serializers.IntegerField(required=False)
    statement_date = serializers.DateField()
    from_date = serializers.DateField(required=False, allow_null=True)
    closing_balance = serializers.CharField(max_length=30)
    notes = serializers.CharField(required=False, allow_blank=True)
    lines = LineIn(many=True)


def _inputs(lines) -> list[payables.LineInput]:
    return [
        payables.LineInput(
            date=line["date"],
            reference=line.get("reference", ""),
            description=line.get("description", ""),
            debit=line.get("debit") or "0",
            credit=line.get("credit") or "0",
        )
        for line in lines
    ]


def _summary(s: SupplierStatement) -> dict:
    return {
        "id": s.pk,
        "supplier": {"id": s.supplier_id, "code": s.supplier.code, "name": s.supplier.name},
        "currency": s.currency.code,
        "from_date": s.from_date,
        "statement_date": s.statement_date,
        "closing_balance": _money(s.closing_balance),
        "status": s.status,
        "created_by": s.created_by.full_name,
    }


def _ours(row: dict) -> dict:
    return {
        "date": row["date"],
        "reference": row["reference"],
        "document": row["document"],
        "link": row["link"],
        "amount": _money(row["amount"]),
    }


def _line(line) -> dict:
    return {
        "line_no": line.line_no,
        "date": line.date,
        "reference": line.reference,
        "description": line.description,
        "debit": _money(line.debit),
        "credit": _money(line.credit),
    }


def _detail(s: SupplierStatement, user) -> dict:
    result = payables.reconcile(s)
    body = _summary(s)
    body |= {
        "notes": s.notes,
        "lines": [_line(x) for x in s.lines.all()],
        "checked_by": s.checked_by.full_name if s.checked_by_id else None,
        "checked_at": s.checked_at,
        "check_note": s.check_note,
        "can_edit": s.status == SupplierStatement.Status.OPEN and payables.can_enter(user),
        "can_check": s.status == SupplierStatement.Status.OPEN and payables.can_check(user),
        "reconciliation": {
            "from": result["from"],
            "to": result["to"],
            "matched": [
                {"line": _line(line), "ours": _ours(ours), "difference": _money(diff)}
                for line, ours, diff in result["matched"]
            ],
            "theirs_only": [_line(x) for x in result["theirs_only"]],
            "ours_only": [{"side": side, **_ours(row)} for side, row in result["ours_only"]],
            "their_balance": _money(result["their_balance"]),
            "our_balance": None if result["our_balance"] is None else _money(result["our_balance"]),
            "difference": None if result["difference"] is None else _money(result["difference"]),
        },
    }
    return body


class StatementListView(_Payables):
    def get(self, request):
        if not payables.can_view(request.user):
            return Response([])
        rows = SupplierStatement.objects.select_related("supplier", "currency", "created_by")
        if request.query_params.get("supplier"):
            rows = rows.filter(supplier_id=request.query_params["supplier"])
        return Response([_summary(s) for s in rows[:500]])

    def post(self, request):
        data = StatementIn(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        supplier = Supplier.objects.filter(pk=values.pop("supplier", None)).first()
        lines = _inputs(values.pop("lines"))
        try:
            made = payables.create(request.user, supplier, lines=lines, **values)
        except PurchasingError as error:
            return _error(error)
        return Response(_detail(made, request.user), status=status.HTTP_201_CREATED)


class StatementDetailView(_Payables):
    def get(self, request, pk):
        return Response(_detail(get_object_or_404(SupplierStatement, pk=pk), request.user))

    def put(self, request, pk):
        statement = get_object_or_404(SupplierStatement, pk=pk)
        data = StatementIn(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("supplier", None)
        lines = _inputs(values.pop("lines"))
        try:
            statement = payables.save(request.user, statement, lines=lines, **values)
        except PurchasingError as error:
            return _error(error)
        return Response(_detail(statement, request.user))

    def delete(self, request, pk):
        try:
            payables.delete(request.user, get_object_or_404(SupplierStatement, pk=pk))
        except PurchasingError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StatementImportView(_Payables):
    """Reads an uploaded statement (Excel or CSV) and returns its lines to check; nothing is
    saved until the statement is saved."""

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return _error("Choose the file.")
        try:
            lines = payables.parse(upload.read(), upload.name)
        except PurchasingError as error:
            return _error(error)
        return Response({"lines": lines})


class StatementCheckView(_Payables):
    # The service allows the Accountant only.
    access_write_level = "view"

    def post(self, request, pk):
        statement = get_object_or_404(SupplierStatement, pk=pk)
        try:
            statement = payables.check(request.user, statement, str(request.data.get("note", "")))
        except PurchasingError as error:
            return _error(error)
        return Response(_detail(statement, request.user))
