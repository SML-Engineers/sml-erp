# ruff: noqa: F811 - the fixtures of test_payments are imported and used by name
"""Petty cash, the imprest way (backlog P2-17)."""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting.models import Account
from apps.banking import petty
from apps.banking.models import PettyExpense
from apps.banking.services import BankingError
from apps.core.models import Division
from apps.masters import banking
from apps.payments import services as payments
from apps.vouchers import services as vouchers
from apps.vouchers.models import Voucher
from apps.vouchers.services import CodingInput

from .test_access import as_user, person
from .test_payments import (  # noqa: F401 - fixtures used by name
    accountant,
    cash,
    cashier,
    clerk,
    director,
    fresh,
    memory_storage,
)
from .test_vouchers import payee

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()
D = Decimal


@pytest.fixture
def custodian():
    return person("sunil@sml.lk", "store_supervisor", all_divisions=True)


@pytest.fixture
def box(accountant, custodian):
    return banking.create_account(
        accountant,
        code="pc-ws",
        kind="petty_cash",
        name="Workshop petty cash",
        custodian=custodian.pk,
        float_amount="10000.00",
        division="WS",
        ledger_account=Account.objects.get(number="1020").pk,
    )


def slip(name="slip.pdf", content=b"%PDF-1.4 slip"):
    return SimpleUploadedFile(name, content)


def spend(user, box, amount, **extra):
    values = {
        "expense_date": TODAY,
        "paid_to": "Hardware shop",
        "description": "Bolts and nuts",
        "amount": amount,
        "slip": slip(content=f"%PDF-1.4 {amount} {extra}".encode()),
    } | extra
    return petty.record(user, box, **values)


def expense_account():
    return Account.objects.get(number="6210")


@pytest.fixture
def two(custodian, box):
    first = spend(custodian, box, "1500.00", ledger=expense_account())
    second = spend(custodian, box, "800.00", paid_to="Three-wheel", description="Transport")
    return first, second


def test_the_custodian_records_expenses_within_the_float(two, custodian, box):
    first, _ = two
    assert first.number.startswith(f"PE{TODAY:%y%m}")
    assert (petty.status(first), first.division.code) == ("open", "WS")
    money = petty.figures(box)
    assert (money["spent"], money["cash_in_hand"]) == (D("2300.00"), D("7700.00"))
    with pytest.raises(BankingError, match="Only 7,700.00 of the float"):
        spend(custodian, box, "8000.00")


def test_only_the_custodian_records_and_a_slip_is_needed(custodian, box):
    stranger = person("other@sml.lk", "store_supervisor", all_divisions=True)
    with pytest.raises(BankingError, match="Only the custodian"):
        spend(stranger, box, "100.00")
    with pytest.raises(BankingError, match="Attach the slip"):
        spend(custodian, box, "100.00", slip=None)
    with pytest.raises(BankingError, match="PDF, JPG or PNG"):
        spend(custodian, box, "100.00", slip=slip("x.txt", b"hello"))


def test_the_clerk_makes_the_top_up_voucher(two, clerk, box):
    first, second = two
    voucher = petty.replenish(clerk, box, payee=payee("Sunil", "employee", "S0101"))
    assert (voucher.voucher_type.code, voucher.total_amount, voucher.status) == (
        "PCH",
        D("2300.00"),
        "draft",
    )
    lines = list(voucher.lines.order_by("line_no"))
    assert [(x.invoice_no, x.amount) for x in lines] == [
        (first.number, D("1500.00")),
        (second.number, D("800.00")),
    ]
    assert lines[0].account.number == "6210" and lines[1].account is None
    assert voucher.attachments.count() == 2
    first.refresh_from_db()
    assert petty.status(first) == "on_voucher"
    with pytest.raises(BankingError, match="no petty cash expenses waiting"):
        petty.replenish(clerk, box, payee=voucher.payee)
    with pytest.raises(DatabaseError, match="never changes"), transaction.atomic():
        PettyExpense.objects.filter(pk=first.pk).update(amount=D("1"))
    with pytest.raises(DatabaseError, match="never deleted"), transaction.atomic():
        PettyExpense.objects.filter(pk=first.pk).delete()


def test_paying_the_voucher_tops_the_float_up(two, clerk, accountant, director, cashier, cash, box):
    voucher = petty.replenish(clerk, box, payee=payee("Sunil", "employee", "S0101"))
    vouchers.submit(clerk, voucher)
    vouchers.code_lines(
        accountant,
        fresh(voucher),
        [
            CodingInput(
                line_no=2, account=expense_account(), division=Division.objects.get(code="WS")
            )
        ],
    )
    vouchers.approve(accountant, fresh(voucher))
    vouchers.approve(director, fresh(voucher))
    payments.record(
        cashier,
        fresh(voucher),
        account=cash,
        method="cash",
        amount="2300.00",
        payment_date=TODAY,
    )
    first, _ = two
    first.refresh_from_db()
    assert petty.status(first) == "paid_back"
    assert petty.figures(box)["cash_in_hand"] == D("10000.00")


def test_a_rejected_voucher_frees_the_expenses(two, clerk, accountant, box):
    voucher = petty.replenish(clerk, box, payee=payee("Sunil", "employee", "S0101"))
    vouchers.submit(clerk, voucher)
    vouchers.reject(accountant, fresh(voucher), "Slips unclear")
    assert fresh(voucher).status == Voucher.Status.REJECTED
    again = petty.replenish(clerk, box, payee=fresh(voucher).payee)
    assert again.total_amount == D("2300.00")


def test_through_the_api(custodian, box):
    client = as_user(custodian)
    made = client.post(
        f"/api/v1/petty-cash/{box.pk}/expenses/",
        {
            "expense_date": str(TODAY),
            "paid_to": "Hardware shop",
            "description": "Bolts",
            "amount": "250.00",
            "slip": slip(),
        },
        format="multipart",
    )
    assert made.status_code == 201, made.content
    floats = client.get("/api/v1/petty-cash/").json()
    assert [(f["code"], f["cash_in_hand"], f["can_record"]) for f in floats] == [
        ("PC-WS", "9750.00", True)
    ]
