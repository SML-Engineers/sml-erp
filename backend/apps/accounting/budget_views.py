"""Budget API (P2-22). Rules live in budgets.py. Anyone with Accounting access sees budgets;
the Accountant prepares them; the approval engine checks who may approve."""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.models import Division
from apps.core.permissions import AreaAccess

from . import budgets
from .budgets import BudgetError, LineInput
from .models import Account, Budget

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _Budgets(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _m(value) -> str:
    return f"{value:.2f}"


def _summary(b: Budget) -> dict:
    return {
        "id": b.pk,
        "year_start": b.year_start,
        "label": budgets.label(b.year_start),
        "version": b.version,
        "status": b.status,
        "notes": b.notes,
        "created_by": b.created_by.full_name,
        "created_at": b.created_at,
        "approved_at": b.approved_at,
        "income": _m(budgets.total(b, "income")),
        "costs": _m(budgets.total(b, "cost")),
    }


def _detail(b: Budget, user) -> dict:
    year = budgets.months(b.year_start)
    state = approvals.state_of(budgets.DOC, b.pk)
    editable = b.status == Budget.Status.DRAFT and b.created_by_id == user.pk
    body = _summary(b) | {
        "months": [m.isoformat()[:7] for m in year],
        "rows": [
            {
                "account": {
                    "id": r["account"].pk,
                    "number": r["account"].number,
                    "name": r["account"].name,
                    "account_type": r["account"].account_type,
                },
                "division": r["division"].code,
                "amounts": {m.isoformat()[:7]: _m(v) for m, v in r["amounts"].items()},
                "total": _m(sum(r["amounts"].values(), Decimal("0"))),
            }
            for r in budgets._grid(b)
        ],
        "can_edit": editable,
        "can_approve": budgets.can_approve(user, b),
        "approval": None
        if state is None
        else {
            "status": state.status,
            "history": [
                {
                    "action": row.action,
                    "action_label": row.get_action_display(),
                    "by": row.user.full_name,
                    "at": row.acted_at,
                    "reason": row.reason,
                }
                for row in approvals.history(budgets.DOC, b.pk)
            ],
        },
    }
    if editable:
        body["accounts"] = [
            {"id": a.pk, "number": a.number, "name": a.name, "account_type": a.account_type}
            for a in budgets.budget_accounts().order_by("account_type", "number", "name")
        ]
        body["divisions"] = list(
            Division.objects.filter(is_active=True).order_by("code").values_list("code", flat=True)
        )
    return body


class BudgetListView(_Budgets):
    def get(self, request):
        rows = Budget.objects.select_related("created_by")[:100]
        current = budgets.year_start_of(date.today())
        return Response(
            {
                "current_year": current.year,
                "current_label": budgets.label(current),
                "can_manage": budgets.can_manage(request.user),
                "budgets": [_summary(b) for b in rows],
            }
        )

    def post(self, request):
        try:
            year = int(request.data.get("year"))
            made = budgets.start(request.user, year, str(request.data.get("notes", "")))
        except (TypeError, ValueError):
            return _error("Give the year the budget starts in.")
        except BudgetError as error:
            return _error(error)
        return Response(_detail(made, request.user), status=status.HTTP_201_CREATED)


def _lines(data) -> list[LineInput]:
    rows = data.get("rows")
    if not isinstance(rows, list):
        raise BudgetError("Give the budget's rows.")
    accounts = Account.objects.in_bulk(
        [r.get("account") for r in rows if isinstance(r, dict) and str(r.get("account")).isdigit()]
    )
    divisions = {d.code: d for d in Division.objects.all()}
    out = []
    for n, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise BudgetError(f"Row {n} is not readable.")
        account = accounts.get(int(row["account"])) if str(row.get("account")).isdigit() else None
        division = divisions.get(str(row.get("division") or "").upper())
        if account is None or division is None:
            raise BudgetError(f"Row {n}: choose an account and a division.")
        amounts = row.get("amounts") or {}
        if not isinstance(amounts, dict):
            raise BudgetError(f"Row {n} is not readable.")
        for month, value in amounts.items():
            text = str(value if value is not None else "").replace(",", "").strip()
            if not text:
                continue
            if isinstance(value, float):
                raise BudgetError(f"Row {n}: amounts are sent as text.")
            try:
                amount = Decimal(text)
                day = date.fromisoformat(f"{month}-01")
            except (InvalidOperation, ValueError):
                raise BudgetError(f"Row {n}: {month} {text!r} is not an amount.") from None
            out.append(LineInput(account, division, day, amount))
    return out


class BudgetDetailView(_Budgets):
    def get(self, request, pk):
        return Response(_detail(get_object_or_404(Budget, pk=pk), request.user))

    def put(self, request, pk):
        found = get_object_or_404(Budget, pk=pk)
        try:
            saved = budgets.save_lines(
                request.user, found, _lines(request.data), notes=request.data.get("notes")
            )
        except BudgetError as error:
            return _error(error)
        return Response(_detail(saved, request.user))

    def delete(self, request, pk):
        try:
            budgets.discard(request.user, get_object_or_404(Budget, pk=pk))
        except BudgetError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BudgetExportView(_Budgets):
    def get(self, request, pk):
        found = get_object_or_404(Budget, pk=pk)
        reply = HttpResponse(budgets.export_workbook(found), content_type=XLSX)
        name = f"budget-{budgets.label(found.year_start)}-v{found.version}.xlsx"
        reply["Content-Disposition"] = f'attachment; filename="{name}"'
        return reply


class BudgetImportView(_Budgets):
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        found = get_object_or_404(Budget, pk=pk)
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose an Excel file to import.")
        if uploaded.size > budgets.MAX_BYTES:
            return _error("The file must be 5 MB or smaller.")
        try:
            saved = budgets.import_file(request.user, found, uploaded.read())
        except BudgetError as error:
            return _error(error)
        return Response(_detail(saved, request.user))


class BudgetActionView(_Budgets):
    action = "submit"

    def get_permissions(self):
        # Approving, returning and rejecting: the approval engine checks the approving role.
        if self.action != "submit":
            self.access_write_level = "view"
        return super().get_permissions()

    def post(self, request, pk):
        found = get_object_or_404(Budget, pk=pk)
        text = str(request.data.get("comment") or request.data.get("reason") or "")
        act = {
            "submit": budgets.submit,
            "approve": budgets.approve,
            "return": budgets.send_back,
            "reject": budgets.reject,
        }[self.action]
        try:
            done = act(request.user, found, text)
        except BudgetError as error:
            return _error(error)
        return Response(_detail(Budget.objects.get(pk=done.pk), request.user))
