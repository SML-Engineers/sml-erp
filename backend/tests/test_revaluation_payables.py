# ruff: noqa: F811 - the fixtures of test_payment_cancellations are imported and used by name
"""Month-end revaluation of an open dollar supplier invoice (backlog P2-21).

The invoice is USD 12,500.00 booked at 300.00; USD is 310.00 today, so at this month's end we
owe more in LKR: an unrealised loss, reversed on the first day of the next month."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting import revaluation

from .test_payment_cancellations import (  # noqa: F401 - fixtures used by name
    accountant,
    cashier,
    clerk,
    director,
    memory_storage,
    pay,
    usd_bank,
    usd_voucher,
)

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
END = revaluation.month_end(TODAY)
D = Decimal


def lines(entry):
    return [
        (x.account.system_role or x.account.number, x.debit, x.credit)
        for x in entry.lines.order_by("line_no")
    ]


def test_an_open_dollar_supplier_invoice_is_a_loss_when_the_dollar_rises(accountant, usd_voucher):
    run = revaluation.prepare(accountant, END)
    (line,) = run.lines.all()
    assert (line.kind, line.supplier.name, line.currency.code) == (
        "payable",
        "Shenzhen Moulds Co",
        "USD",
    )
    assert (line.open_amount, line.carried_lkr, line.revalued_lkr) == (
        D("12500.00"),
        D("3750000.00"),
        D("3875000.00"),
    )
    assert line.difference == D("-125000.00")
    run = revaluation.post(accountant, run)
    assert lines(run.journal_entry) == [
        ("accounts_payable", 0, D("125000.00")),
        ("unrealised_exchange", D("125000.00"), 0),
    ]
    payable = run.journal_entry.lines.order_by("line_no").first()
    assert payable.supplier == line.supplier and payable.division == line.division
    assert lines(run.reversal_entry) == [
        ("accounts_payable", D("125000.00"), 0),
        ("unrealised_exchange", 0, D("125000.00")),
    ]
    assert run.reversal_entry.entry_date == END + timedelta(days=1)


def test_what_is_left_after_a_part_payment_is_revalued(accountant, cashier, usd_bank, usd_voucher):
    pay(cashier, usd_voucher, usd_bank, "5000.00")  # USD 5,000.00 at 310.00
    run = revaluation.prepare(accountant, END, {usd_bank.pk: "-5000.00"})
    payable = run.lines.get(kind="payable")
    assert (payable.open_amount, payable.carried_lkr, payable.difference) == (
        D("7500.00"),
        D("2250000.00"),
        D("-75000.00"),
    )
    # The account paid out at today's rate already: nothing changes on it.
    bank = run.lines.get(kind="balance")
    assert (bank.carried_lkr, bank.revalued_lkr, bank.difference) == (
        D("-1550000.00"),
        D("-1550000.00"),
        D("0.00"),
    )
