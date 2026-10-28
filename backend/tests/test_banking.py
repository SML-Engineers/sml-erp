"""Company bank and cash accounts, cheque books, division defaults (backlog P0-14)."""

from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.core.models import AuditEvent, Division
from apps.masters import banking, services
from apps.masters.models import ChequeLeaf, CompanyAccount
from apps.masters.services import MastersError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def cashier():
    return person("cashier@sml.lk", "cashier", all_divisions=True)


@pytest.fixture
def current(accountant):
    return banking.create_account(
        accountant,
        code="com-cur",
        kind="current",
        name="Commercial Bank current",
        bank_name="Commercial Bank",
        branch="Seeduwa",
        account_number="1000234567",
    )


# --- Accounts ---------------------------------------------------------------------------


def test_the_accountant_adds_bank_cash_and_petty_cash_accounts(accountant, current):
    assert current.code == "COM-CUR" and current.currency.code == "LKR"
    cash = banking.create_account(accountant, code="CASH", kind="cash", name="Office cash")
    petty = banking.create_account(
        accountant,
        code="PETTY-WS",
        kind="petty_cash",
        name="Workshop petty cash",
        custodian=accountant.pk,
        float_amount="25000.00",
        division="WS",
    )
    assert cash.account_number == ""
    assert petty.float_amount == Decimal("25000.00") and petty.division.code == "WS"


@pytest.mark.parametrize(
    "values, why",
    [
        ({"kind": "current", "bank_name": "", "account_number": "1000999888"}, "bank name"),
        ({"kind": "current", "bank_name": "BOC", "account_number": "12"}, "4 to 34"),
        ({"kind": "petty_cash"}, "custodian and its float"),
        (
            {
                "kind": "savings",
                "bank_name": "BOC",
                "account_number": "1000999888",
                "float_amount": "5",
            },
            "Only petty cash",
        ),
        (
            {
                "kind": "current",
                "bank_name": "BOC",
                "account_number": "1000999888",
                "currency": "XYZ",
            },
            "active currency",
        ),
        ({"kind": "loan"}, "kind of account"),
    ],
)
def test_an_account_must_be_valid(accountant, values, why):
    with pytest.raises(MastersError, match=why):
        banking.create_account(accountant, code="X1", name="Test", **values)


def test_the_same_bank_account_cannot_be_entered_twice(accountant, current):
    with pytest.raises(MastersError, match="already in the list"):
        banking.create_account(
            accountant,
            code="COM2",
            kind="current",
            name="Duplicate",
            bank_name="commercial bank",
            account_number="1000234567",
        )


def test_only_the_accountant_changes_bank_accounts(cashier):
    with pytest.raises(MastersError, match="Only the Accountant"):
        banking.create_account(cashier, code="X1", kind="cash", name="Cash")
    director = person("director@sml.lk", "director", all_divisions=True)
    admin = person("admin@sml.lk", "system_admin", all_divisions=True)
    assert as_user(director).get("/api/v1/company-accounts/").status_code == 200
    assert as_user(admin).get("/api/v1/company-accounts/").status_code == 403
    response = as_user(director).post(
        "/api/v1/company-accounts/", {"code": "X1", "kind": "cash", "name": "Cash"}, format="json"
    )
    assert response.status_code == 403


def test_closing_an_account_needs_a_reason_and_is_audited(accountant, current):
    with pytest.raises(MastersError, match="reason"):
        banking.update_account(accountant, current, {"is_active": False})
    banking.update_account(accountant, current, {"is_active": False}, reason="account closed")
    assert AuditEvent.objects.filter(event="company_account_closed").exists()


def test_a_used_account_keeps_its_code_number_and_currency(accountant, current):
    banking.add_cheque_book(accountant, current, first=100001, last=100050)
    banking.use_cheque(accountant, current, 100001, status="issued")
    with pytest.raises(MastersError, match="code cannot change"):
        banking.update_account(accountant, current, {"code": "COM-NEW"})
    with pytest.raises(MastersError, match="cannot change"):
        banking.update_account(accountant, current, {"account_number": "2000111222"})
    services.mark_used(CompanyAccount.objects.get(pk=current.pk))
    with pytest.raises(DatabaseError), transaction.atomic():
        CompanyAccount.objects.filter(pk=current.pk).delete()


# --- Division defaults ------------------------------------------------------------------


def test_each_division_gets_a_default_bank_account(accountant, current):
    response = as_user(accountant).put(
        "/api/v1/company-accounts/division-defaults/",
        {"division": "IM", "account": current.pk},
        format="json",
    )
    assert response.status_code == 200, response.json()
    rows = {r["division"]: r["account"] for r in response.json()}
    assert rows["IM"] == {"id": current.pk, "code": "COM-CUR"}
    assert rows["WS"] is None


def test_a_default_must_be_an_open_bank_account_and_cannot_be_closed(accountant, current):
    cash = banking.create_account(accountant, code="CASH", kind="cash", name="Office cash")
    with pytest.raises(MastersError, match="open bank account"):
        banking.set_division_default(accountant, Division.objects.get(code="WS"), cash)
    banking.set_division_default(accountant, Division.objects.get(code="WS"), current)
    with pytest.raises(MastersError, match="another default first"):
        banking.update_account(accountant, current, {"is_active": False}, reason="x")


# --- Cheque books -----------------------------------------------------------------------


def test_cheque_books_hold_a_range_and_give_the_next_number(accountant, current):
    book = banking.add_cheque_book(accountant, current, first=1, last=50, digits=6)
    assert banking.format_cheque(book, 1) == "000001"
    assert banking.next_cheque(current) == (book, 1)
    banking.use_cheque(accountant, current, 1, status="issued")
    banking.use_cheque(accountant, current, 3, status="issued")
    assert banking.next_cheque(current)[1] == 2
    assert banking.book_summary(book) == {"leaves": 50, "used": 2, "left": 48, "next": 2}


@pytest.mark.parametrize(
    "first, last, digits, why",
    [
        (50, 10, 6, "not be below"),
        (1, 2000, 6, "at most 1000"),
        (1, 50, 1, "digits"),
    ],
)
def test_a_cheque_book_must_be_valid(accountant, current, first, last, digits, why):
    with pytest.raises(MastersError, match=why):
        banking.add_cheque_book(accountant, current, first=first, last=last, digits=digits)


def test_cheque_books_cannot_overlap(accountant, current):
    banking.add_cheque_book(accountant, current, first=100001, last=100050)
    with pytest.raises(MastersError, match="overlap"):
        banking.add_cheque_book(accountant, current, first=100040, last=100090)
    banking.add_cheque_book(accountant, current, first=100051, last=100100)


def test_only_current_accounts_have_cheque_books(accountant):
    savings = banking.create_account(
        accountant,
        code="SAV",
        kind="savings",
        name="Savings",
        bank_name="BOC",
        account_number="7000111222",
    )
    with pytest.raises(MastersError, match="current accounts"):
        banking.add_cheque_book(accountant, savings, first=1, last=10)


def test_a_cheque_number_is_used_once_ever(accountant, current):
    banking.add_cheque_book(accountant, current, first=1, last=10)
    banking.use_cheque(accountant, current, 5, status="issued")
    with pytest.raises(MastersError, match="already been used"):
        banking.use_cheque(accountant, current, 5, status="spoiled", reason="x")
    with pytest.raises(MastersError, match="not in an active cheque book"):
        banking.use_cheque(accountant, current, 11, status="issued")
    with pytest.raises(DatabaseError), transaction.atomic():
        ChequeLeaf.objects.filter(number=5).update(status="spoiled")
    with pytest.raises(DatabaseError), transaction.atomic():
        ChequeLeaf.objects.filter(number=5).delete()


def test_the_cashier_records_a_spoiled_cheque_with_a_reason(accountant, cashier, current):
    banking.add_cheque_book(accountant, current, first=1, last=10)
    url = f"/api/v1/company-accounts/{current.pk}/cheques/"
    assert as_user(cashier).post(url, {"number": 1}, format="json").status_code == 400
    response = as_user(cashier).post(
        url, {"number": 1, "reason": "wrong amount written"}, format="json"
    )
    assert response.status_code == 201, response.json()
    assert response.json()["number"] == "000001" and response.json()["status"] == "spoiled"
    register = as_user(cashier).get(url).json()
    assert register["next"] == "000002"


def test_a_closed_cheque_book_gives_no_more_numbers(accountant, current):
    book = banking.add_cheque_book(accountant, current, first=1, last=10)
    banking.close_book(accountant, book, reason="lost")
    assert banking.next_cheque(current) is None
    with pytest.raises(MastersError, match="not in an active cheque book"):
        banking.use_cheque(accountant, current, 2, status="issued")
