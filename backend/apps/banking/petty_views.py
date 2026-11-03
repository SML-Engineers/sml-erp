"""Petty cash API (P2-17). Rules live in petty.py."""

from datetime import date

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounting.models import Account
from apps.core.models import Division
from apps.core.permissions import AreaAccess
from apps.masters.models import CompanyAccount, Supplier

from . import petty
from .models import PettyExpense
from .services import BankingError


class _Petty(APIView):
    # Custodians may be anyone the Admin names; the service checks who may do what.
    parser_classes = [MultiPartParser, FormParser, JSONParser]


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _expense(e: PettyExpense) -> dict:
    return {
        "id": e.pk,
        "number": e.number,
        "expense_date": e.expense_date,
        "paid_to": e.paid_to,
        "description": e.description,
        "amount": f"{e.amount:.2f}",
        "ledger": None
        if e.ledger_id is None
        else {"id": e.ledger_id, "number": e.ledger.number, "name": e.ledger.name},
        "division": e.division.code if e.division_id else None,
        "slip_name": e.slip_name,
        "status": petty.status(e),
        "voucher": None
        if e.voucher_id is None
        else {"id": e.voucher_id, "number": e.voucher.number},
        "created_by": e.created_by.full_name,
    }


def _float(account: CompanyAccount, user) -> dict:
    money = petty.figures(account)
    return {
        "id": account.pk,
        "code": account.code,
        "name": account.name,
        "custodian": account.custodian.full_name if account.custodian_id else None,
        "division": account.division.code if account.division_id else None,
        "can_record": petty.can_keep(user, account),
        **{k: f"{v:.2f}" for k, v in money.items()},
    }


class PettyFloatListView(_Petty):
    def get(self, request):
        rows = petty.floats(request.user).select_related("custodian", "division")
        return Response([_float(a, request.user) for a in rows])


def _account(user, pk) -> CompanyAccount:
    return get_object_or_404(petty.floats(user).select_related("custodian", "division"), pk=pk)


class PettyExpenseListView(_Petty):
    def get(self, request, pk):
        account = _account(request.user, pk)
        rows = account.petty_expenses.select_related("ledger", "division", "voucher", "created_by")
        wanted = request.query_params.get("status")
        found = [_expense(e) for e in rows[:2000]]
        if wanted:
            found = [row for row in found if row["status"] == wanted]
        return Response({"float": _float(account, request.user), "expenses": found})

    def post(self, request, pk):
        account = _account(request.user, pk)
        data = request.data
        try:
            when = date.fromisoformat(str(data.get("expense_date") or ""))
        except ValueError:
            return _error("Give the date of the expense.")
        ledger = Account.objects.filter(pk=data.get("ledger") or 0).first()
        division = Division.objects.filter(code=str(data.get("division") or "").upper()).first()
        try:
            made = petty.record(
                request.user,
                account,
                expense_date=when,
                paid_to=str(data.get("paid_to") or ""),
                description=str(data.get("description") or ""),
                amount=str(data.get("amount") or ""),
                slip=request.FILES.get("slip"),
                ledger=ledger,
                division=division,
            )
        except BankingError as error:
            return _error(error)
        return Response(_expense(made), status=status.HTTP_201_CREATED)


def _get_expense(user, pk) -> PettyExpense:
    found = get_object_or_404(PettyExpense.objects.select_related("account"), pk=pk)
    _account(user, found.account_id)
    return found


class PettyExpenseDetailView(_Petty):
    def delete(self, request, pk):
        try:
            petty.remove(request.user, _get_expense(request.user, pk))
        except BankingError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PettySlipView(_Petty):
    def get(self, request, pk):
        expense = _get_expense(request.user, pk)
        return FileResponse(
            expense.slip.open("rb"), content_type=expense.slip_type, filename=expense.slip_name
        )


class PettyReplenishView(_Petty):
    """The Clerk: a draft Petty Cash voucher for the expenses not yet paid back."""

    permission_classes = [AreaAccess]
    access_area = "vouchers"
    access_write_level = "enter"

    def post(self, request, pk):
        account = _account(request.user, pk)
        payee = Supplier.objects.filter(pk=request.data.get("payee") or 0).first()
        division = Division.objects.filter(
            code=str(request.data.get("division") or "").upper()
        ).first()
        ids = request.data.get("expenses")
        expenses = list(account.petty_expenses.filter(pk__in=ids)) if ids else None
        try:
            voucher = petty.replenish(
                request.user, account, payee=payee, division=division, expenses=expenses
            )
        except BankingError as error:
            return _error(error)
        return Response(
            {"voucher": {"id": voucher.pk, "number": voucher.number}},
            status=status.HTTP_201_CREATED,
        )
