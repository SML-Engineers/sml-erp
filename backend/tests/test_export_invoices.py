"""Export invoices and exchange differences (backlog P2-09, spec 5.5, 6; IAS 21): invoices in
the customer's currency at the rate of the invoice date, receipts and advances at their own
rates, and the realised exchange gain or loss posted."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import services as chart
from apps.accounting import taxes
from apps.accounting.models import Account, DetailType, TaxCode, TaxComponent
from apps.core.models import Company, Division
from apps.masters import banking, currencies, customers
from apps.masters.models import Currency
from apps.sales import (
    advances,
    credit_notes,
    invoice_printing,
    invoices,
    orders,
    receipts,
    receivables,
    services,
    workflow,
)
from apps.sales.credit_notes import LineInput as CreditLine
from apps.sales.models import AdvanceSetOff, ReceiptAllocation
from apps.sales.orders import Delivery
from apps.sales.orders import LineInput as OrderLine
from apps.sales.receipts import Allocation
from apps.sales.services import LineInput as QuoteLine
from apps.sales.services import SalesError

from . import test_tax_invoices as base
from .test_access import person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
D = Decimal
INVOICED = TODAY - timedelta(days=20)


@pytest.fixture
def cashier():
    return person("cashier@sml.lk", "cashier", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def stores():
    return person("stores@sml.lk", "store_supervisor", all_divisions=True)


def usd():
    return Currency.objects.get(code="USD")


@pytest.fixture(autouse=True)
def setup(accountant):
    for code, rate in (("SSCL", "2.125"), ("VAT", "18")):
        component = TaxComponent.objects.get(code=code)
        taxes.add_rate(accountant, component, effective_from=base.GO_LIVE, rate=rate)
    Company.objects.filter(pk=1).update(name="SML Engineers (Pvt) Ltd", tin="134567890")
    Division.objects.filter(code="WS").update(tax_invoice_code="W1")
    # USD 300.00 until ten days ago, then 310.00.
    currencies.set_rate(currency=usd(), on_date=TODAY - timedelta(days=60), rate="300.00")
    currencies.set_rate(currency=usd(), on_date=TODAY - timedelta(days=10), rate="310.00")


def bank_account(accountant, code, currency, number):
    return banking.create_account(
        accountant,
        code=code,
        kind="current",
        name=f"Commercial Bank {currency}",
        bank_name="Commercial Bank",
        account_number=f"10002345{number}",
        currency=currency,
        ledger_account=chart.create_account(
            accountant,
            name=f"Commercial Bank {currency}",
            account_type="bank",
            detail_type=DetailType.objects.get(name="Current account"),
            number=number,
        ).pk,
    )


@pytest.fixture
def usd_bank(accountant):
    return bank_account(accountant, "com-usd", "USD", "1040")


@pytest.fixture
def lkr_bank(accountant):
    return bank_account(accountant, "com-lkr", "LKR", "1030")


@pytest.fixture
def buyer(executive):
    return customers.create_customer(
        executive,
        {"name": "Mahindra Gears", "currency": "USD", "is_export": True, "country": "India"},
    )


@pytest.fixture
def order(executive, director, buyer):
    """100 gear blanks at USD 25.00 for an Indian buyer, no VAT (exempt), USD 2,500.00."""
    return order_for(executive, director, buyer)


def order_for(executive, director, buyer, **values):
    q = services.save(
        executive,
        None,
        customer=buyer,
        division=Division.objects.get(code="WS"),
        **values,
        lines=[
            QuoteLine(
                description="Gear blank, EN8",
                quantity="100",
                unit_price="25.00",
                tax_code=TaxCode.objects.get(code="EXEMPT"),
            )
        ],
    )
    workflow.submit(executive, q)
    workflow.approve(director, q)
    q = workflow.record_outcome(executive, q, accepted=True, reason="price")
    o = orders.from_quotation(executive, q)
    orders.save(
        executive,
        o,
        customer_po="MG/PO/55",
        payment_terms="30 days",
        lines=[
            OrderLine(
                quantity=line.quantity,
                quotation_line=line.quotation_line,
                schedule=[Delivery(TODAY, line.quantity)],
            )
            for line in o.lines.order_by("line_no")
        ],
    )
    return orders.confirm(executive, o)


def issue(stores, accountant, order, quantity="100"):
    """Delivered and invoiced twenty days ago, when USD was 300.00."""
    base.deliver(stores, order, quantity)
    draft = invoices.create(accountant, order)
    invoices.save(accountant, draft, invoices.Header(invoice_date=INVOICED))
    return invoices.issue(accountant, draft)


@pytest.fixture
def invoice(order, stores, accountant):
    return issue(stores, accountant, order)


def lines(entry):
    return [(x.account.number, x.debit, x.credit) for x in entry.lines.order_by("line_no")]


def role(name):
    return Account.objects.get(system_role=name).number


def pay(cashier, account, invoice, amount, **extra):
    return receipts.record(
        cashier,
        **{
            "customer": invoice.customer,
            "method": "transfer",
            "account": account,
            "amount": amount,
            "receipt_date": TODAY,
            "reference": "SWIFT 8812",
            "allocations": [Allocation(invoice, amount)],
        }
        | extra,
    )


# --- The invoice --------------------------------------------------


def test_the_invoice_is_in_dollars_and_booked_in_rupees_at_its_date_s_rate(invoice):
    assert (invoice.currency.code, invoice.total_amount) == ("USD", D("2500.00"))
    assert (invoice.exchange_rate, invoice.rate_date) == (D("300.000000"), TODAY - timedelta(60))
    assert invoice.total_lkr == D("750000.00")
    assert invoice.amount_in_words == "USD Two Thousand Five Hundred Only"
    assert lines(invoice.journal_entry) == [
        (role("accounts_receivable"), D("750000.00"), 0),
        ("4010", 0, D("750000.00")),
    ]
    assert invoice.journal_entry.lines.order_by("line_no").first().customer == invoice.customer
    text = invoice_printing.render(invoice, compress=False)
    assert rb"Rate \(USD\)" in text and b"Total in LKR: 750,000.00" in text


def test_no_rate_no_invoice(order, stores, accountant):
    base.deliver(stores, order, "100")
    draft = invoices.create(accountant, order)
    with pytest.raises(SalesError, match="no USD rate on or before"):
        invoices.save(accountant, draft, invoices.Header(invoice_date=TODAY - timedelta(days=90)))


# --- Receipts and exchange differences --------------------------------------------------


def test_a_receipt_at_a_higher_rate_posts_an_exchange_gain(invoice, cashier, accountant, usd_bank):
    made = receipts.approve(accountant, pay(cashier, usd_bank, invoice, "2500.00"))
    assert (made.currency.code, made.exchange_rate, made.amount_lkr) == (
        "USD",
        D("310.000000"),
        D("775000.00"),
    )
    assert lines(made.journal_entry) == [
        ("1040", D("775000.00"), 0),
        (role("accounts_receivable"), 0, D("750000.00")),
        (role("exchange_gain"), 0, D("25000.00")),
    ]
    assert receipts.lkr_left(invoice) == 0 and receipts.open_amount(invoice) == 0


def test_part_payments_clear_the_receivable_to_the_cent(invoice, cashier, accountant, usd_bank):
    first = receipts.approve(accountant, pay(cashier, usd_bank, invoice, "1000.01"))
    assert ReceiptAllocation.objects.get(receipt=first).carrying_lkr == D("300003.00")
    last = receipts.approve(accountant, pay(cashier, usd_bank, invoice, "1499.99"))
    assert ReceiptAllocation.objects.get(receipt=last).carrying_lkr == D("449997.00")
    assert receipts.lkr_left(invoice) == 0


def test_a_receipt_at_a_lower_rate_posts_an_exchange_loss(invoice, cashier, accountant, usd_bank):
    currencies.set_rate(currency=usd(), on_date=TODAY, rate="295.50")
    made = receipts.approve(accountant, pay(cashier, usd_bank, invoice, "2500.00"))
    assert lines(made.journal_entry) == [
        ("1040", D("738750.00"), 0),
        (role("accounts_receivable"), 0, D("750000.00")),
        (role("exchange_loss"), D("11250.00"), 0),
    ]


def test_dollars_go_into_a_dollar_account(invoice, cashier, lkr_bank):
    with pytest.raises(SalesError, match="the money goes into a USD account"):
        pay(cashier, lkr_bank, invoice, "100.00")


def test_one_receipt_pays_invoices_of_one_currency(
    invoice, buyer, cashier, usd_bank, executive, director, stores, accountant
):
    local = issue(stores, accountant, order_for(executive, director, buyer, currency="LKR"))
    assert local.currency.code == "LKR"
    with pytest.raises(SalesError, match="invoices of one currency"):
        receipts.record(
            cashier,
            customer=buyer,
            method="transfer",
            account=usd_bank,
            amount="20.00",
            receipt_date=TODAY,
            reference="SWIFT 1",
            allocations=[Allocation(invoice, "10.00"), Allocation(local, "10.00")],
        )
    made = pay(cashier, usd_bank, invoice, "10.00")
    with pytest.raises(DatabaseError, match="another currency"), transaction.atomic():
        ReceiptAllocation.objects.create(receipt=made, invoice=local, amount=D("1.00"))


# --- Advances and credit notes --------------------------------------------------


def test_a_dollar_advance_is_set_off_at_its_own_rate(order, stores, accountant, cashier, usd_bank):
    paid = advances.approve(
        accountant,
        advances.record(
            cashier,
            customer=order.customer,
            account=usd_bank,
            method="transfer",
            amount="500.00",
            receipt_date=TODAY,
            reference="SWIFT 7001",
            sales_order=order,
        ),
    )
    assert paid.amount_lkr == D("155000.00")  # at 310.00
    invoice = issue(stores, accountant, order)  # at 300.00
    set_off = AdvanceSetOff.objects.get(advance=paid)
    assert (set_off.amount, set_off.amount_lkr, set_off.carrying_lkr) == (
        D("500.00"),
        D("155000.00"),
        D("150000.00"),
    )
    assert lines(set_off.journal_entry) == [
        (role("customer_advances"), D("155000.00"), 0),
        (role("accounts_receivable"), 0, D("150000.00")),
        (role("exchange_gain"), 0, D("5000.00")),
    ]
    paid.refresh_from_db()
    assert (advances.balance(paid), paid.set_off_lkr) == (0, D("155000.00"))
    assert receipts.open_amount(invoice) == D("2000.00")


def test_a_credit_note_reverses_at_the_invoice_s_rate(invoice, executive, director):
    note = credit_notes.create(
        executive,
        invoice,
        lines=[CreditLine(invoice.lines.get(), "100.00")],
        kind="price",
        reason="Late delivery discount",
    )
    note = credit_notes.approve(director, credit_notes.submit(executive, note))
    assert note.total_lkr == D("30000.00")
    assert lines(note.journal_entry) == [
        ("4010", D("30000.00"), 0),
        (role("accounts_receivable"), 0, D("30000.00")),
    ]


# --- Receivables in rupees --------------------------------------------------


def test_aging_and_credit_control_count_rupees_at_the_invoice_s_rate(invoice, accountant):
    (row,) = receivables.aging(accountant, TODAY)
    assert (row["current"], row["total"], row["ledger"]) == ("750000.00", "750000.00", "750000.00")
    figures = receivables.exposure(invoice.customer)
    assert figures.owed == D("750000.00")
