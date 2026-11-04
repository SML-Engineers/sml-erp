# ruff: noqa: F811 - the fixtures of test_export_invoices are imported and used by name
"""Month-end revaluation of open foreign-currency invoices and bank balances (backlog P2-21).

The export invoice is USD 2,500.00 booked at 300.00 twenty days ago; USD is 310.00 from ten
days ago, so at this month's end it is worth more in LKR."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import revaluation
from apps.accounting.models import Account, JournalEntry, Revaluation, RevaluationLine
from apps.accounting.revaluation import RevaluationError
from apps.banking.models import BankStatement, StatementTemplate
from apps.sales import receipts

from .test_access import as_user
from .test_export_invoices import (  # noqa: F401 - fixtures used by name
    accountant,
    buyer,
    cashier,
    director,
    executive,
    invoice,
    order,
    pay,
    setup,
    stores,
    usd_bank,
)

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
END = revaluation.month_end(TODAY)
D = Decimal


def role(name):
    return Account.objects.get(system_role=name)


def lines(entry):
    return [
        (x.account.system_role or x.account.number, x.debit, x.credit)
        for x in entry.lines.order_by("line_no")
    ]


def test_an_open_dollar_invoice_is_revalued_and_reversed_the_next_day(invoice, accountant):
    run = revaluation.prepare(accountant, END)
    (line,) = run.lines.all()
    assert (line.kind, line.document, line.currency.code) == ("receivable", invoice.number, "USD")
    assert (line.open_amount, line.carried_lkr) == (D("2500.00"), D("750000.00"))
    assert (line.rate, line.revalued_lkr, line.difference) == (
        D("310.000000"),
        D("775000.00"),
        D("25000.00"),
    )
    assert (run.open_items_total, run.balances_total) == (D("25000.00"), D("0"))

    run = revaluation.post(accountant, run)
    assert run.status == "posted" and run.balances_entry is None
    assert run.journal_entry.entry_date == END
    assert lines(run.journal_entry) == [
        ("accounts_receivable", D("25000.00"), 0),
        ("unrealised_exchange", 0, D("25000.00")),
    ]
    first = run.journal_entry.lines.order_by("line_no").first()
    assert (first.customer, first.division.code) == (invoice.customer, "WS")
    # Reversed on the first day of the next month: the invoice is back at its own rate.
    assert run.reversal_entry.entry_date == END + timedelta(days=1)
    assert run.reversal_entry.reversal_of == run.journal_entry
    assert lines(run.reversal_entry) == [
        ("accounts_receivable", 0, D("25000.00")),
        ("unrealised_exchange", D("25000.00"), 0),
    ]
    assert receipts.lkr_left(invoice) == D("750000.00")


def test_a_dollar_bank_balance_is_revalued_and_kept(invoice, cashier, accountant, usd_bank):
    # USD 1,000.00 received fifteen days ago, at 300.00: the bank carries LKR 300,000.00.
    receipts.approve(
        accountant, pay(cashier, usd_bank, invoice, "1000.00", receipt_date=TODAY - timedelta(15))
    )
    with pytest.raises(RevaluationError, match="Give the balance .* of: com-usd"):
        revaluation.prepare(accountant, END)

    run = revaluation.prepare(accountant, END, {usd_bank.pk: "1000.00"})
    by_kind = {x.kind: x for x in run.lines.all()}
    assert (by_kind["receivable"].open_amount, by_kind["receivable"].difference) == (
        D("1500.00"),
        D("15000.00"),  # 450,000.00 carried, 465,000.00 at 310.00
    )
    bank = by_kind["balance"]
    assert (bank.carried_lkr, bank.revalued_lkr, bank.difference) == (
        D("300000.00"),
        D("310000.00"),
        D("10000.00"),
    )
    assert bank.balance_from == f"Typed by {accountant.full_name}"
    assert (run.open_items_total, run.balances_total) == (D("15000.00"), D("10000.00"))

    run = revaluation.post(accountant, run)
    assert lines(run.balances_entry) == [
        ("1040", D("10000.00"), 0),
        ("exchange_gain", 0, D("10000.00")),
    ]
    # The bank keeps its new value: only the invoices' part is reversed.
    assert not JournalEntry.objects.filter(reversal_of=run.balances_entry).exists()
    assert revaluation.ledger_balance(usd_bank.ledger_account, END + timedelta(1)) == D("310000.00")


def test_the_month_s_bank_statement_gives_the_balance(invoice, cashier, accountant, usd_bank):
    receipts.approve(
        accountant, pay(cashier, usd_bank, invoice, "1000.00", receipt_date=TODAY - timedelta(15))
    )
    BankStatement.objects.create(
        account=usd_bank,
        template=StatementTemplate.objects.first(),
        file_name="usd.xlsx",
        sha256="a" * 64,
        from_date=TODAY.replace(day=1),
        to_date=TODAY,
        opening_balance=D("0"),
        closing_balance=D("990.00"),  # USD 10.00 of bank charges not yet in the books
        imported_by=accountant,
    )
    run = revaluation.prepare(accountant, END)
    bank = run.lines.get(kind="balance")
    assert bank.open_amount == D("990.00")
    assert bank.balance_from == f"Bank statement to {TODAY:%d %b %Y}"
    assert bank.difference == D("306900.00") - D("300000.00")


def test_a_posted_month_never_changes(invoice, accountant):
    run = revaluation.post(accountant, revaluation.prepare(accountant, END))
    with pytest.raises(RevaluationError, match="posted already"):
        revaluation.prepare(accountant, END)
    with pytest.raises(RevaluationError, match="never removed"):
        revaluation.discard(accountant, run)
    with transaction.atomic(), pytest.raises(DatabaseError, match="never changes"):
        Revaluation.objects.filter(pk=run.pk).update(open_items_total=0)
    with transaction.atomic(), pytest.raises(DatabaseError, match="never change"):
        RevaluationLine.objects.filter(revaluation=run).update(difference=0)


def test_a_draft_is_worked_out_again_or_discarded(invoice, accountant):
    run = revaluation.prepare(accountant, END)
    again = revaluation.prepare(accountant, END)
    assert again.pk == run.pk and again.lines.count() == 1
    revaluation.discard(accountant, again)
    assert not Revaluation.objects.exists()


def test_only_the_accountant_and_not_a_month_to_come(invoice, accountant, cashier):
    with pytest.raises(RevaluationError, match="Only the Accountant"):
        revaluation.prepare(cashier, END)
    with pytest.raises(RevaluationError, match="not come yet"):
        revaluation.prepare(accountant, END + timedelta(days=1))


def test_nothing_in_foreign_currency_nothing_to_post(accountant):
    run = revaluation.prepare(accountant, END)
    assert run.lines.count() == 0
    with pytest.raises(RevaluationError, match="nothing to post"):
        revaluation.post(accountant, run)


def test_the_screens_api(invoice, accountant, cashier, usd_bank):
    api = as_user(accountant)
    got = api.get("/api/v1/revaluations/", {"month_end": END.isoformat()})
    assert got.status_code == 200, got.data
    assert [a["code"] for a in got.data["accounts"]] == ["com-usd"]
    made = api.post(
        "/api/v1/revaluations/",
        {"month_end": END.isoformat(), "balances": {str(usd_bank.pk): "0.00"}},
        format="json",
    )
    assert made.status_code == 201, made.data
    assert [x["kind"] for x in made.data["lines"]] == ["receivable"]
    assert made.data["lines"][0]["difference"] == "25000.00"
    posted = api.post(f"/api/v1/revaluations/{made.data['id']}/post/")
    assert posted.status_code == 200, posted.data
    assert posted.data["status"] == "posted" and posted.data["reversal_entry"]
    assert as_user(cashier).post("/api/v1/revaluations/", {}, format="json").status_code == 403
