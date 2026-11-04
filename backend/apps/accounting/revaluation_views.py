"""Month-end revaluation API (P2-21). Rules live in revaluation.py; Accounting access is
needed, and entering it to work out and post a month."""

from datetime import date

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess

from . import revaluation
from .models import Revaluation
from .revaluation import RevaluationError


class _Revaluation(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _m(value) -> str:
    return f"{value:.2f}"


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _run(r: Revaluation) -> dict:
    lines = r.lines.select_related(
        "currency", "division", "customer", "supplier", "company_account"
    )
    return {
        "id": r.pk,
        "month_end": r.month_end,
        "status": r.status,
        "open_items_total": _m(r.open_items_total),
        "balances_total": _m(r.balances_total),
        "journal_entry": r.journal_entry.number if r.journal_entry_id else None,
        "reversal_entry": r.reversal_entry.number if r.reversal_entry_id else None,
        "balances_entry": r.balances_entry.number if r.balances_entry_id else None,
        "prepared_by": r.prepared_by.full_name,
        "posted_by": r.posted_by.full_name if r.posted_by_id else None,
        "lines": [
            {
                "id": x.pk,
                "kind": x.kind,
                "document": x.document,
                "link": x.link,
                "party": (x.customer or x.supplier or x.company_account).name,
                "division": x.division.code,
                "currency": x.currency.code,
                "open_amount": _m(x.open_amount),
                "carried_lkr": _m(x.carried_lkr),
                "rate": f"{x.rate.normalize():f}",
                "rate_date": x.rate_date,
                "revalued_lkr": _m(x.revalued_lkr),
                "difference": _m(x.difference),
                "balance_from": x.balance_from,
            }
            for x in lines
        ],
    }


class RevaluationListView(_Revaluation):
    def get(self, request):
        """The months revalued, and the foreign-currency bank and cash accounts with the
        balance their statement gives for the suggested month."""
        month = _day(request.query_params.get("month_end")) or revaluation.suggested_month()
        month = revaluation.month_end(month)
        accounts = []
        for a in revaluation.foreign_accounts():
            found = revaluation.statement_balance(a, month)
            accounts.append(
                {
                    "id": a.pk,
                    "code": a.code,
                    "name": a.name,
                    "currency": a.currency.code,
                    "statement_balance": _m(found[0]) if found else None,
                    "statement_date": found[1] if found else None,
                }
            )
        rows = Revaluation.objects.select_related(
            "journal_entry", "reversal_entry", "balances_entry", "prepared_by", "posted_by"
        )
        return Response(
            {
                "suggested_month": month,
                "accounts": accounts,
                "runs": [_run(r) for r in rows[:60]],
            }
        )

    def post(self, request):
        balances = request.data.get("balances") or {}
        if not isinstance(balances, dict):
            return _error(RevaluationError("Balances are given per account."))
        try:
            made = revaluation.prepare(
                request.user,
                _day(request.data.get("month_end")) or revaluation.suggested_month(),
                balances,
            )
        except (RevaluationError, ValueError) as error:
            return _error(error)
        return Response(_run(made), status=status.HTTP_201_CREATED)


class RevaluationActionView(_Revaluation):
    action = "post"

    def post(self, request, pk):
        run = get_object_or_404(Revaluation, pk=pk)
        try:
            if self.action == "post":
                run = revaluation.post(request.user, run)
            else:
                revaluation.discard(request.user, run)
                return Response(status=status.HTTP_204_NO_CONTENT)
        except RevaluationError as error:
            return _error(error)
        return Response(_run(run))
