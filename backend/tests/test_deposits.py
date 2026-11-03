# ruff: noqa: F811 - the fixtures of test_customer_receipts are imported and used by name
"""Customers' cheques: deposit slips, cleared and returned cheques (backlog P2-14)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.banking import services
from apps.banking.services import BankingError
from apps.sales import receipts, receivables
from apps.sales.models import CustomerReceipt

from .test_access import as_user, person
from .test_customer_receipts import (  # noqa: F401 - fixtures used by name
    accountant,
    bank,
    cash,
    cashier,
    director,
    executive,
    lines,
    order,
    pay,
    setup,
    stores,
    two,
)

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()
D = Decimal
S = CustomerReceipt.Status


@pytest.fixture
def cheque(two, cashier, accountant):
    one, _ = two
    made = pay(
        cashier,
        None,
        (one, "20000.00"),
        method="cheque",
        reference="004512",
        cheque_bank="Sampath Bank",
    )
    return receipts.approve(accountant, made)


def slip(cashier, bank, *cheques, **extra):
    return services.deposit(
        cashier, account=bank, deposit_date=TODAY, receipts=list(cheques), **extra
    )


def test_a_posted_cheque_waits_in_hand_until_deposited(cheque, cashier, bank):
    assert services.received_status(cheque) == "in_hand"
    assert list(services.in_hand()) == [cheque]
    made = slip(cashier, bank, cheque, slip_no="SB-1")
    assert made.number.startswith(f"DP{TODAY:%y%m}") and made.total == D("20000.00")
    assert lines(made.journal_entry) == [
        ("1030", D("20000.00"), 0, None, None),
        ("1300", 0, D("20000.00"), None, None),
    ]
    cheque.refresh_from_db()
    assert services.received_status(cheque) == "deposited"
    assert list(services.in_hand()) == []
    with pytest.raises(BankingError, match="not a cheque waiting"):
        slip(cashier, bank, cheque)


def test_only_an_lkr_bank_account_and_only_due_cheques(two, cashier, accountant, bank, cash):
    one, _ = two
    later = receipts.approve(
        accountant,
        pay(cashier, None, (one, "100.00"), method="cheque", cheque_date=TODAY + timedelta(5)),
    )
    assert later.status == S.POST_DATED
    with pytest.raises(BankingError, match="not a cheque waiting"):
        slip(cashier, bank, later)
    now = receipts.approve(accountant, pay(cashier, None, (one, "50.00"), method="cheque"))
    with pytest.raises(BankingError, match="LKR bank accounts"):
        slip(cashier, cash, now)


def test_a_clerk_does_not_deposit(cheque, bank):
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    with pytest.raises(BankingError, match="Cashier or the Accountant"):
        slip(clerk, bank, cheque)


def test_a_deposited_cheque_is_marked_cleared(cheque, cashier, bank):
    with pytest.raises(BankingError, match="has not been deposited"):
        services.clear_received(cashier, cheque, TODAY)
    slip(cashier, bank, cheque)
    services.clear_received(cashier, cheque, TODAY)
    cheque.refresh_from_db()
    assert services.received_status(cheque) == "cleared"
    with pytest.raises(BankingError, match="has cleared"):
        services.return_cheque(cashier, cheque, returned_on=TODAY, reason="Refer to drawer")


def test_a_returned_cheque_reverses_the_receipt_from_the_bank(two, cheque, cashier, bank):
    one, _ = two
    open_before = receipts.open_amount(one)
    slip(cashier, bank, cheque)
    with pytest.raises(BankingError, match="reason"):
        services.return_cheque(cashier, cheque, returned_on=TODAY, reason=" ")
    back = services.return_cheque(cashier, cheque, returned_on=TODAY, reason="Refer to drawer")
    assert (back.status, back.returned_on) == (S.RETURNED, TODAY)
    assert lines(back.return_entry) == [
        ("1030", 0, D("20000.00"), "WS", None),
        ("1100", D("20000.00"), 0, "WS", one.customer_id),
    ]
    # The invoice is open again, now and in the aging.
    assert receipts.open_amount(one) == open_before + D("20000.00")
    assert receivables.open_at([one], TODAY)[one.pk] == one.total_amount
    with pytest.raises(DatabaseError), transaction.atomic():
        CustomerReceipt.objects.filter(pk=back.pk).update(status=S.POSTED)


def test_a_cheque_returned_before_it_was_deposited_leaves_undeposited_funds(cheque, cashier):
    back = services.return_cheque(cashier, cheque, returned_on=TODAY, reason="Stopped")
    assert ("1300", 0, D("20000.00"), "WS", None) in lines(back.return_entry)


def test_the_database_keeps_a_posted_receipt(cheque):
    with pytest.raises(DatabaseError), transaction.atomic():
        CustomerReceipt.objects.filter(pk=cheque.pk).update(status=S.RETURNED)


def test_the_register_and_a_deposit_through_the_api(cheque, cashier, bank):
    client = as_user(cashier)
    rows = client.get("/api/v1/cheques/received/").json()
    assert [(r["number"], r["status"]) for r in rows] == [(cheque.number, "in_hand")]
    made = client.post(
        "/api/v1/deposits/",
        {"account": bank.pk, "deposit_date": str(TODAY), "receipts": [cheque.pk]},
        format="json",
    )
    assert made.status_code == 201, made.content
    assert made.json()["total"] == "20000.00"
    back = client.post(
        f"/api/v1/cheques/received/{cheque.pk}/return/",
        {"on": str(TODAY), "reason": "Account closed"},
        format="json",
    )
    assert back.status_code == 200, back.content
    assert back.json()["status"] == "returned"
