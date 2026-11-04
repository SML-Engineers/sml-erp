"""Trial balance, balance sheet and general ledger API (P2-03). Figures come from
reports.py; every one carries the account id, so the screen can open the ledger behind it,
and every ledger line carries its entry and the page of the document that posted it.

All need Financial reports: View. Someone who does not see all divisions must choose one of
theirs. ?export=xlsx or pdf gives the same rows as the screen."""

from datetime import date
from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import exports
from apps.core.access import division_scope, sees_all_divisions
from apps.core.exports import STRONG, Column
from apps.core.permissions import AreaAccess

from . import cash_flow, reports, sources
from .catalogue import TYPES
from .models import Account
from .services import AccountingError


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _date(value, what, default=None):
    if not value and default is not None:
        return default
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise AccountingError(f"The {what} must be a date, for example 2026-10-31.") from None


def division_of(request):
    """The division asked for (None for the company), within the user's divisions."""
    code = (request.query_params.get("division") or "").upper()
    if code:
        division = division_scope(request.user).filter(code=code).first()
        if division is None:
            raise AccountingError("Unknown division.")
        return division
    if not sees_all_divisions(request.user):
        raise AccountingError("Choose one of your divisions.")
    return None


def _money(amount: Decimal) -> str:
    return f"{amount:.2f}"


def _ref(ref: reports.AccountRef) -> dict:
    return {
        "id": ref.id,
        "number": ref.number,
        "name": ref.name,
        "account_type": ref.account_type,
        "account_type_label": TYPES[ref.account_type][0],
    }


def _subtitle(text: str, division) -> str:
    who = f"Division {division.code} {division.name}" if division else "Company"
    return f"{text} · {who} · printed {timezone.localtime():%d/%m/%Y %H:%M}"


class _Report(APIView):
    permission_classes = [AreaAccess]
    access_area = "financial_reports"


class TrialBalanceView(_Report):
    def get(self, request):
        params = request.query_params
        try:
            as_at = _date(params.get("as_at"), "date", timezone.localdate())
            division = division_of(request)
            rows, other = reports.trial_balance(
                as_at,
                division,
                compare=params.get("compare", ""),
                roll_up_subaccounts=params.get("sub") == "rollup",
            )
        except AccountingError as error:
            return _error(error)
        fmt = (params.get("export") or "").lower()
        if fmt in exports.FORMATS:
            columns = [
                Column("number", "No.", width=0.6),
                Column("account", "Account", width=2.6),
                Column("type", "Type", width=1.2),
                Column("debit", f"Debit {as_at:%d/%m/%Y}", "money"),
                Column("credit", f"Credit {as_at:%d/%m/%Y}", "money"),
            ]
            if other:
                columns += [
                    Column("compare_debit", f"Debit {other:%d/%m/%Y}", "money"),
                    Column("compare_credit", f"Credit {other:%d/%m/%Y}", "money"),
                ]
            flat = [
                {
                    "number": r.account.number,
                    "account": r.account.name,
                    "type": TYPES[r.account.account_type][0],
                    "debit": r.debit or None,
                    "credit": r.credit or None,
                    "compare_debit": r.compare_debit or None,
                    "compare_credit": r.compare_credit or None,
                }
                for r in rows
            ]
            return exports.response(
                fmt,
                title="Trial balance",
                subtitle=_subtitle(f"As at {as_at:%d/%m/%Y}", division),
                columns=columns,
                rows=flat,
                filename=f"trial-balance-{as_at}",
                user=request.user,
            )
        return Response(
            {
                "as_at": as_at,
                "compare_date": other,
                "division": division.code if division else None,
                "rows": [
                    {
                        "account": _ref(r.account),
                        "debit": _money(r.debit),
                        "credit": _money(r.credit),
                        "compare_debit": _money(r.compare_debit),
                        "compare_credit": _money(r.compare_credit),
                    }
                    for r in rows
                ],
                "total_debit": _money(sum((r.debit for r in rows), Decimal("0"))),
                "total_credit": _money(sum((r.credit for r in rows), Decimal("0"))),
                "compare_total_debit": _money(sum((r.compare_debit for r in rows), Decimal("0"))),
                "compare_total_credit": _money(sum((r.compare_credit for r in rows), Decimal("0"))),
            }
        )


class BalanceSheetView(_Report):
    def get(self, request):
        params = request.query_params
        try:
            as_at = _date(params.get("as_at"), "date", timezone.localdate())
            division = division_of(request)
            sections, other = reports.balance_sheet(
                as_at,
                division,
                compare=params.get("compare", ""),
                roll_up_subaccounts=params.get("sub") == "rollup",
            )
        except AccountingError as error:
            return _error(error)
        body = []
        for s in sections:
            total, compare_total = s.total()
            body.append(
                {
                    "key": s.key,
                    "title": s.title,
                    "rows": [
                        {
                            "label": r.label,
                            "kind": r.kind,
                            "account": _ref(r.account) if r.account else None,
                            "amount": _money(r.amount),
                            "compare": _money(r.compare),
                        }
                        for r in s.rows
                    ],
                    "total": _money(total),
                    "compare_total": _money(compare_total),
                }
            )
        fmt = (params.get("export") or "").lower()
        if fmt in exports.FORMATS:
            columns = [
                Column("label", "", width=3.5),
                Column("amount", f"{as_at:%d/%m/%Y}", "money"),
            ]
            if other:
                columns.append(Column("compare", f"{other:%d/%m/%Y}", "money"))
            flat = []
            for s in body:
                flat.append({"label": s["title"], STRONG: True})
                for r in s["rows"]:
                    flat.append(
                        {
                            "label": f"    {r['label']}",
                            "amount": r["amount"],
                            "compare": r["compare"] if other else None,
                        }
                    )
                flat.append(
                    {
                        "label": f"Total {s['title'].lower()}",
                        "amount": s["total"],
                        "compare": s["compare_total"] if other else None,
                        STRONG: True,
                    }
                )
            return exports.response(
                fmt,
                title="Balance sheet",
                subtitle=_subtitle(f"As at {as_at:%d/%m/%Y}", division),
                columns=columns,
                rows=flat,
                filename=f"balance-sheet-{as_at}",
                user=request.user,
                totals=False,
            )
        return Response(
            {
                "as_at": as_at,
                "compare_date": other,
                "division": division.code if division else None,
                "sections": body,
            }
        )


class GeneralLedgerView(_Report):
    def get(self, request):
        params = request.query_params
        today = timezone.localdate()
        try:
            date_to = _date(params.get("to"), "end date", today)
            date_from = _date(params.get("from"), "start date", date_to.replace(day=1))
            division = division_of(request)
            account = None
            if params.get("account"):
                if not str(params["account"]).isdigit():
                    raise AccountingError("Unknown account.")
                account = get_object_or_404(Account, pk=int(params["account"]))
            ledgers = reports.general_ledger(
                date_from,
                date_to,
                division,
                account=account,
                with_subaccounts=params.get("sub") == "include",
            )
        except AccountingError as error:
            return _error(error)
        pages = sources.paths(
            (line.source_type, line.source_id) for ledger in ledgers for line in ledger.lines
        )
        fmt = (params.get("export") or "").lower()
        if fmt in exports.FORMATS:
            columns = [
                Column("date", "Date", "date", 0.8),
                Column("number", "Entry", width=1.0),
                Column("narration", "Narration", width=3.0),
                Column("division", "Div.", width=0.5),
                Column("debit", "Debit", "money"),
                Column("credit", "Credit", "money"),
                Column("balance", "Balance", "money"),
            ]
            flat = []
            for ledger in ledgers:
                name = f"{ledger.account.number} {ledger.account.name}".strip()
                flat.append({"narration": name, STRONG: True})
                flat.append(
                    {
                        "date": date_from,
                        "narration": "Balance brought forward",
                        "balance": ledger.opening,
                    }
                )
                for line in ledger.lines:
                    text = line.narration
                    if line.description:
                        text = f"{text} · {line.description}"
                    if line.supplier:
                        text = f"{text} · {line.supplier}"
                    flat.append(
                        {
                            "date": line.entry_date,
                            "number": line.number,
                            "narration": text,
                            "division": line.division,
                            "debit": line.debit or None,
                            "credit": line.credit or None,
                            "balance": line.balance,
                        }
                    )
                flat.append(
                    {
                        "date": date_to,
                        "narration": "Balance carried forward",
                        "balance": ledger.closing,
                        STRONG: True,
                    }
                )
            return exports.response(
                fmt,
                title="General ledger",
                subtitle=_subtitle(f"{date_from:%d/%m/%Y} to {date_to:%d/%m/%Y}", division),
                columns=columns,
                rows=flat,
                filename=f"general-ledger-{date_from}-{date_to}",
                user=request.user,
                totals=False,
            )
        return Response(
            {
                "from": date_from,
                "to": date_to,
                "division": division.code if division else None,
                "accounts": [
                    {
                        "account": _ref(ledger.account),
                        "opening": _money(ledger.opening),
                        "closing": _money(ledger.closing),
                        "total_debit": _money(sum((x.debit for x in ledger.lines), Decimal("0"))),
                        "total_credit": _money(sum((x.credit for x in ledger.lines), Decimal("0"))),
                        "lines": [
                            {
                                "entry": {"id": x.entry_id, "number": x.number},
                                "entry_date": x.entry_date,
                                "narration": x.narration,
                                "description": x.description,
                                "division": x.division or None,
                                "supplier": x.supplier or None,
                                "debit": _money(x.debit),
                                "credit": _money(x.credit),
                                "balance": _money(x.balance),
                                "source_type": x.source_type,
                                "source_id": x.source_id,
                                "source_page": pages.get((x.source_type, x.source_id)),
                            }
                            for x in ledger.lines
                        ],
                    }
                    for ledger in ledgers
                ],
            }
        )


# --- Cash flow statement and home page tiles (P2-24) ------------------------------------------


def _flow_rows(st) -> list[dict]:
    rows = []
    for section, title in (
        (st.operating, "Operating activities"),
        (st.investing, "Investing activities"),
        (st.financing, "Financing activities"),
    ):
        rows.append({"section": section.key, "label": title, "kind": "heading", "amount": ""})
        for r in section.rows:
            rows.append(
                {
                    "section": section.key,
                    "label": r.label,
                    "kind": "line",
                    "amount": _money(r.amount),
                    "account": r.account.pk if r.account else None,
                }
            )
        rows.append(
            {
                "section": section.key,
                "label": f"Net cash from {title.lower()}",
                "kind": "total",
                "amount": _money(section.total),
            }
        )
    return rows


class CashFlowView(_Report):
    """The cash flow statement (indirect method) for a period, for the company."""

    def get(self, request):
        params = request.query_params
        today = timezone.localdate()
        try:
            if not sees_all_divisions(request.user):
                raise AccountingError("The cash flow statement is for the whole company.")
            date_from = _date(params.get("from"), "start date", today.replace(day=1))
            date_to = _date(params.get("to"), "end date", today)
            st = cash_flow.statement(date_from, date_to)
        except AccountingError as error:
            return _error(error)
        rows = _flow_rows(st)
        summary = [
            ("Net change in cash", st.net_change),
            ("Cash at the start", st.opening_cash),
            ("Cash at the end", st.closing_cash),
        ]
        fmt = (params.get("export") or "").lower()
        if fmt in exports.FORMATS:
            flat = [
                {
                    "label": r["label"],
                    "amount": r["amount"],
                    STRONG: r["kind"] != "line",
                }
                for r in rows
            ] + [{"label": k, "amount": _money(v), STRONG: True} for k, v in summary]
            return exports.response(
                fmt,
                title="Cash flow statement",
                subtitle=_subtitle(
                    f"{date_from:%d/%m/%Y} to {date_to:%d/%m/%Y} · indirect method", None
                ),
                columns=[Column("label", "", width=3.0), Column("amount", "LKR", "money")],
                rows=flat,
                filename=f"cash-flow-{date_from}-{date_to}",
                user=request.user,
            )
        return Response(
            {
                "from": date_from,
                "to": date_to,
                "profit": _money(st.profit),
                "rows": rows,
                "operating": _money(st.operating.total),
                "investing": _money(st.investing.total),
                "financing": _money(st.financing.total),
                "net_change": _money(st.net_change),
                "opening_cash": _money(st.opening_cash),
                "closing_cash": _money(st.closing_cash),
                "difference": _money(st.difference),
            }
        )


class FinancialDashboardView(_Report):
    """The financial tiles of the home page, for the company or one division."""

    def get(self, request):
        scope = list(division_scope(request.user).order_by("code"))
        code = (request.query_params.get("division") or "").upper()
        if code:
            division = next((d for d in scope if d.code == code), None)
            if division is None:
                return _error("Unknown division.")
        elif sees_all_divisions(request.user):
            division = None
        else:
            division = scope[0] if scope else None
            if division is None:
                return _error("Choose one of your divisions.")
        data = cash_flow.dashboard(request.user, division)

        def money(value):
            return None if value is None else _money(value)

        def tile(values: dict) -> dict:
            return {k: money(v) if isinstance(v, Decimal) else v for k, v in values.items()}

        return Response(
            {
                "today": data["today"],
                "division": data["division"],
                "company": sees_all_divisions(request.user),
                "divisions": [{"code": d.code, "name": d.name} for d in scope],
                "this_month": tile(data["this_month"]),
                "year_to_date": tile(data["year_to_date"]),
                "cash": tile(data["cash"]),
                "receivables": tile(data["receivables"]),
                "payables": tile(data["payables"]),
            }
        )
