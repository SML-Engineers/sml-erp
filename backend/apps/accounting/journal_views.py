"""Journal, accounting periods and profit and loss API (P0-16). Rules live in journal.py."""

from datetime import date

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import division_scope, sees_all_divisions
from apps.core.permissions import AreaAccess

from . import journal
from .catalogue import TYPES
from .models import Account, JournalEntry, JournalLine
from .services import AccountingError

MAX_ROWS = 500


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _date(value, what):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise AccountingError(f"The {what} must be a date, for example 2026-10-31.") from None


def _summary(entry: JournalEntry) -> dict:
    try:
        reversed_by = entry.reversed_by
    except JournalEntry.DoesNotExist:
        reversed_by = None
    return {
        "id": entry.pk,
        "number": entry.number,
        "entry_date": entry.entry_date,
        "source_type": entry.source_type,
        "source_id": entry.source_id,
        "narration": entry.narration,
        "amount": f"{entry.amount:.2f}" if entry.amount is not None else "0.00",
        "posted_by": entry.posted_by.full_name,
        "posted_at": entry.posted_at,
        "reversal_of": None
        if entry.reversal_of is None
        else {"id": entry.reversal_of_id, "number": entry.reversal_of.number},
        "reversed_by": None
        if reversed_by is None
        else {"id": reversed_by.pk, "number": reversed_by.number},
    }


def _entries():
    return JournalEntry.objects.select_related("posted_by", "reversal_of", "reversed_by").annotate(
        amount=Sum("lines__debit")
    )


class _Journal(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "manage"


class JournalListView(_Journal):
    """Posted entries, newest first. Filters: from, to, q (number or narration), account."""

    def get(self, request):
        rows = _entries()
        params = request.query_params
        try:
            if params.get("from"):
                rows = rows.filter(entry_date__gte=_date(params["from"], "start date"))
            if params.get("to"):
                rows = rows.filter(entry_date__lte=_date(params["to"], "end date"))
        except AccountingError as error:
            return _error(error)
        text = (params.get("q") or "").strip()
        if text:
            rows = rows.filter(Q(number__icontains=text) | Q(narration__icontains=text))
        if params.get("account", "").isdigit():
            used = JournalLine.objects.filter(account_id=int(params["account"]))
            rows = rows.filter(pk__in=used.values("entry_id"))
        return Response([_summary(e) for e in rows[:MAX_ROWS]])


class JournalDetailView(_Journal):
    def get(self, request, pk):
        entry = get_object_or_404(_entries(), pk=pk)
        body = _summary(entry)
        body["lines"] = [
            {
                "line_no": line.line_no,
                "account": {
                    "id": line.account_id,
                    "number": line.account.number,
                    "name": line.account.name,
                },
                "division": line.division.code if line.division else None,
                "supplier": None
                if line.supplier is None
                else {"code": line.supplier.code, "name": line.supplier.name},
                "description": line.description,
                "debit": f"{line.debit:.2f}",
                "credit": f"{line.credit:.2f}",
            }
            for line in entry.lines.select_related("account", "division", "supplier")
        ]
        return Response(body)


class JournalReverseView(_Journal):
    """The Accountant reverses a posted entry, with a reason."""

    def post(self, request, pk):
        entry = get_object_or_404(JournalEntry, pk=pk)
        try:
            on_date = request.data.get("date")
            reversal = journal.reverse(
                request.user,
                entry,
                reason=str(request.data.get("reason", "")),
                on_date=_date(on_date, "date") if on_date else None,
            )
        except AccountingError as error:
            return _error(error)
        return Response(_summary(_entries().get(pk=reversal.pk)), status=status.HTTP_201_CREATED)


class PeriodListView(_Journal):
    def get(self, request):
        year = request.query_params.get("year", "")
        year = int(year) if year.isdigit() and 2000 <= int(year) <= 2100 else date.today().year
        return Response({"year": year, "months": journal.periods(year)})


class PeriodChangeView(_Journal):
    """Close or reopen a month. The service requires the Director's "close period" right."""

    access_write_level = "view"

    def post(self, request, month, action):
        if action not in ("close", "reopen"):
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            first = _date(f"{month}-01", "month")
            journal.set_closed(
                request.user,
                first,
                closed=action == "close",
                reason=str(request.data.get("reason", "")),
            )
        except AccountingError as error:
            return _error(error)
        return Response({"year": first.year, "months": journal.periods(first.year)})


class ProfitAndLossView(APIView):
    """Profit and loss per account for a date range, for one division or the company."""

    permission_classes = [AreaAccess]
    access_area = "financial_reports"

    def get(self, request):
        params = request.query_params
        try:
            date_from = _date(params.get("from", ""), "start date")
            date_to = _date(params.get("to", ""), "end date")
            division = None
            if params.get("division"):
                division = (
                    division_scope(request.user).filter(code=params["division"].upper()).first()
                )
                if division is None:
                    raise AccountingError("Unknown division.")
            elif not sees_all_divisions(request.user):
                raise AccountingError("Choose one of your divisions.")
            totals = journal.profit_and_loss(date_from, date_to, division)
        except AccountingError as error:
            return _error(error)
        accounts = Account.objects.in_bulk(totals.keys())
        rows = [
            {
                "account": {"id": pk, "number": accounts[pk].number, "name": accounts[pk].name},
                "account_type": accounts[pk].account_type,
                "account_type_label": TYPES[accounts[pk].account_type][0],
                "amount": f"{amount:.2f}",
            }
            for pk, amount in sorted(totals.items(), key=lambda item: accounts[item[0]].number)
        ]
        profit = sum(totals.values())
        return Response(
            {
                "from": date_from,
                "to": date_to,
                "division": division.code if division else None,
                "rows": rows,
                "profit": f"{profit:.2f}" if rows else "0.00",
            }
        )
