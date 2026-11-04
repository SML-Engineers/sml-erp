"""Month-end checklist and year-end close API (P2-23). Rules live in close.py: the Accountant
ticks the checklist; only the Director closes and reopens (the service checks the right)."""

from datetime import date, timedelta

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import effective_access
from apps.core.permissions import AreaAccess

from . import close, journal
from .budgets import label, start_month, year_start_of
from .services import AccountingError


class _Close(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _month(text: str) -> date | None:
    try:
        return date.fromisoformat(f"{text}-01")
    except ValueError:
        return None


def _checklist(user, month: date) -> dict:
    items = close.checklist(month)
    return {
        "month": f"{month:%Y-%m}",
        "is_closed": journal.is_closed(month),
        "can_tick": close.can_tick(user),
        "can_close": effective_access(user).can("close_period"),
        "ready": all(i.done for i in items),
        "items": [
            {
                "key": i.key,
                "label": i.label,
                "done": i.done,
                "detail": i.detail,
                "ticked_by": i.ticked_by or None,
                "ticked_at": i.ticked_at,
                "note": i.note,
            }
            for i in items
        ],
    }


class ChecklistView(_Close):
    def get(self, request, month):
        first = _month(month)
        if first is None:
            return _error("Give the month as YYYY-MM.")
        return Response(_checklist(request.user, first))


class TickView(_Close):
    def post(self, request, month):
        first = _month(month)
        if first is None:
            return _error("Give the month as YYYY-MM.")
        try:
            close.tick(
                request.user,
                first,
                str(request.data.get("item", "")),
                str(request.data.get("note", "")),
            )
        except AccountingError as error:
            return _error(error)
        return Response(_checklist(request.user, first), status=status.HTTP_201_CREATED)


def _year(user, year_start: date) -> dict:
    s = close.year_status(year_start)
    return {
        "year": year_start.year,
        "label": s["label"],
        "open_months": [f"{m:%Y-%m}" for m in s["open_months"]],
        "closed": s["closed"] is not None,
        "can_close": effective_access(user).can("close_period"),
        "history": [
            {
                "profit": f"{h.profit:.2f}",
                "entry": h.journal_entry.number,
                "entry_date": h.journal_entry.entry_date,
                "closed_by": h.closed_by.full_name,
                "closed_at": h.closed_at,
                "reopened": h.reopened,
                "reopen_reason": h.reopen_reason,
                "reopen_entry": h.reopen_entry.number if h.reopen_entry_id else None,
                "reopened_by": h.reopened_by.full_name if h.reopened_by_id else None,
                "reopened_at": h.reopened_at,
            }
            for h in s["history"]
        ],
    }


class YearView(_Close):
    def get(self, request):
        given = request.query_params.get("year")
        start = (
            date(int(given), start_month(), 1)
            if str(given or "").isdigit() and 2000 <= int(given) <= 2100
            else year_start_of(year_start_of(date.today()) - timedelta(days=1))
        )
        return Response(_year(request.user, start) | {"label": label(start)})


class YearActionView(_Close):
    action = "close"
    access_write_level = "view"

    def post(self, request, year):
        if not 2000 <= year <= 2100:
            return _error("Give the year the financial year starts in.")
        start = date(year, start_month(), 1)
        try:
            if self.action == "close":
                close.close_year(request.user, start)
            else:
                close.reopen_year(request.user, start, str(request.data.get("reason", "")))
        except AccountingError as error:
            return _error(error)
        return Response(_year(request.user, start))
