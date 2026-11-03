"""Bank reconciliation API (P2-16). Rules live in reconcile.py; the Accountant acts."""

from datetime import date, timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounting.models import Account, JournalEntry
from apps.core.models import Division
from apps.core.permissions import AreaAccess
from apps.masters.models import CompanyAccount

from . import reconcile
from .models import BankReconciliation, BankRule, BankStatementLine
from .services import BankingError


class _Reconcile(APIView):
    permission_classes = [AreaAccess]
    access_area = "banking"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _money(value) -> str | None:
    return None if value is None else f"{value:.2f}"


def _account(pk) -> CompanyAccount:
    return get_object_or_404(
        CompanyAccount.objects.select_related("ledger_account"),
        pk=pk or 0,
        kind__in=reconcile_kinds(),
    )


def reconcile_kinds():
    return [CompanyAccount.Kind.CURRENT, CompanyAccount.Kind.SAVINGS]


def _day(text) -> date:
    try:
        return date.fromisoformat(str(text))
    except ValueError:
        today = timezone.localdate()
        return reconcile.month_end(today.replace(day=1) - timedelta(days=1))


def _line(line: BankStatementLine, items, user) -> dict:
    match = getattr(line, "match", None)
    row = {
        "id": line.pk,
        "date": line.date,
        "description": line.description,
        "reference": line.reference,
        "money_out": _money(line.money_out),
        "money_in": _money(line.money_in),
        "balance": _money(line.balance),
        "match": None
        if match is None
        else {
            "entry": {"id": match.entry_id, "number": match.entry.number},
            "narration": match.entry.narration,
            "posted": match.posted,
            "by": match.matched_by.full_name,
        },
    }
    if match is None:
        row["suggestion"] = reconcile.suggestion(line, items)
        row["coding"] = None if row["suggestion"] else reconcile.coding_for(line)
    return row


class SummaryView(_Reconcile):
    """?account=&period_end=YYYY-MM-DD (default: the end of last month)."""

    def get(self, request):
        account = _account(request.query_params.get("account"))
        period_end = _day(request.query_params.get("period_end"))
        try:
            figures = reconcile.summary(account, period_end)
        except BankingError as error:
            return _error(error)
        start = figures["locked_to"]
        lines = BankStatementLine.objects.filter(account=account, date__lte=period_end)
        if start is not None:
            lines = lines.filter(date__gt=start)
        lines = lines.select_related("account", "match__entry", "match__matched_by").order_by(
            "date", "statement_id", "line_no"
        )
        items = reconcile.book_items(account)
        return Response(
            {
                "account": {"id": account.pk, "code": account.code, "name": account.name},
                "period_end": period_end,
                "locked_to": start,
                "bank_balance": _money(figures["bank_balance"]),
                "book_balance": _money(figures["book_balance"]),
                "unpresented_total": _money(figures["unpresented_total"]),
                "not_in_books_total": _money(figures["not_in_books_total"]),
                "difference": _money(figures["difference"]),
                "unpresented": [i.as_dict() for i in figures["unpresented"]],
                "lines": [_line(x, items, request.user) for x in lines[:3000]],
                "done": [
                    {
                        "period_end": r.period_end,
                        "bank_balance": _money(r.bank_balance),
                        "done_by": r.done_by.full_name,
                        "done_at": r.done_at,
                    }
                    for r in BankReconciliation.objects.filter(account=account)[:24]
                ],
            }
        )


def _get_line(pk) -> BankStatementLine:
    return get_object_or_404(BankStatementLine.objects.select_related("account"), pk=pk or 0)


class CandidatesView(_Reconcile):
    def get(self, request, pk):
        return Response(reconcile.candidates(_get_line(pk)))


class MatchView(_Reconcile):
    def post(self, request):
        line = _get_line(request.data.get("line"))
        entry = get_object_or_404(JournalEntry, pk=request.data.get("entry") or 0)
        try:
            reconcile.match(request.user, line, entry)
        except BankingError as error:
            return _error(error)
        return Response({"ok": True})


class UnmatchView(_Reconcile):
    def post(self, request):
        try:
            reconcile.unmatch(request.user, _get_line(request.data.get("line")))
        except BankingError as error:
            return _error(error)
        return Response({"ok": True})


class PostIn(serializers.Serializer):
    line = serializers.IntegerField()
    account = serializers.IntegerField()
    division = serializers.CharField(max_length=2, required=False, allow_blank=True, default="")
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)


class PostView(_Reconcile):
    def post(self, request):
        body = PostIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        division = None
        if data["division"]:
            division = Division.objects.filter(code=data["division"].upper()).first()
        try:
            reconcile.post_line(
                request.user,
                _get_line(data["line"]),
                account=Account.objects.filter(pk=data["account"]).first(),
                division=division,
                description=data.get("description", ""),
            )
        except BankingError as error:
            return _error(error)
        return Response({"ok": True}, status=status.HTTP_201_CREATED)


class AcceptView(_Reconcile):
    def post(self, request):
        account = _account(request.data.get("account"))
        try:
            made = reconcile.accept_suggestions(
                request.user, account, _day(request.data.get("period_end"))
            )
        except BankingError as error:
            return _error(error)
        return Response({"matched": made})


class FinishView(_Reconcile):
    def post(self, request):
        account = _account(request.data.get("account"))
        try:
            reconcile.finish(
                request.user,
                account,
                _day(request.data.get("period_end")),
                str(request.data.get("note") or ""),
            )
        except BankingError as error:
            return _error(error)
        return Response({"ok": True}, status=status.HTTP_201_CREATED)


def _rule(r: BankRule) -> dict:
    return {
        "id": r.pk,
        "account": None if r.account_id is None else r.account.code,
        "account_id": r.account_id,
        "text": r.text,
        "direction": r.direction,
        "ledger": {"id": r.ledger_id, "number": r.ledger.number, "name": r.ledger.name},
        "division": r.division.code if r.division_id else None,
        "is_active": r.is_active,
    }


class RuleIn(serializers.Serializer):
    account = serializers.IntegerField(required=False, allow_null=True)
    text = serializers.CharField(max_length=100)
    direction = serializers.ChoiceField(choices=BankRule.Direction.values, default="any")
    ledger = serializers.IntegerField()
    division = serializers.CharField(max_length=2, required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(default=True)


def _save_rule(request, rule: BankRule | None):
    reconcile._accountant(request.user)
    body = RuleIn(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    ledger = Account.objects.filter(pk=data["ledger"], is_active=True).first()
    if ledger is None or ledger.account_type in reconcile.NOT_TO_POST:
        raise BankingError("Choose an active account that a statement line can be posted to.")
    rule = rule or BankRule(created_by=request.user)
    rule.account = (
        CompanyAccount.objects.filter(pk=data["account"]).first() if data.get("account") else None
    )
    rule.text = data["text"].strip()
    rule.direction = data["direction"]
    rule.ledger = ledger
    rule.division = (
        Division.objects.filter(code=data["division"].upper()).first() if data["division"] else None
    )
    rule.is_active = data["is_active"]
    if not rule.text:
        raise BankingError("Give the words to look for in the description.")
    rule.save()
    return rule


class RuleListView(_Reconcile):
    def get(self, request):
        rows = BankRule.objects.select_related("account", "ledger", "division")
        return Response([_rule(r) for r in rows])

    def post(self, request):
        try:
            made = _save_rule(request, None)
        except BankingError as error:
            return _error(error)
        return Response(_rule(made), status=status.HTTP_201_CREATED)


class RuleDetailView(_Reconcile):
    def patch(self, request, pk):
        try:
            saved = _save_rule(request, get_object_or_404(BankRule, pk=pk))
        except BankingError as error:
            return _error(error)
        return Response(_rule(saved))
