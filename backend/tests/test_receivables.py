"""Customer statements, receivables aging, credit control and payment reminders (backlog
P2-08, spec 6, 7A; owner, 3 Nov 2026: block until the Director allows the document)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import services as chart
from apps.accounting import taxes
from apps.accounting.models import DetailType, TaxCode, TaxComponent
from apps.core.models import Company, Division, MailAccount, Notification
from apps.masters import banking, customers
from apps.masters.models import Customer
from apps.sales import (
    invoices,
    orders,
    receipts,
    receivables,
    services,
    statement_printing,
    workflow,
)
from apps.sales.models import CreditHold, ReminderSent
from apps.sales.orders import Delivery
from apps.sales.orders import LineInput as OrderLine
from apps.sales.receipts import Allocation
from apps.sales.services import LineInput as QuoteLine
from apps.sales.services import SalesError

from . import test_tax_invoices as base
from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
D = Decimal


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


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


@pytest.fixture(autouse=True)
def setup(accountant):
    for code, rate in (("SSCL", "2.125"), ("VAT", "18")):
        component = TaxComponent.objects.get(code=code)
        taxes.add_rate(accountant, component, effective_from=base.GO_LIVE, rate=rate)
    Company.objects.filter(pk=1).update(name="SML Engineers (Pvt) Ltd", tin="134567890")
    Division.objects.filter(code="WS").update(tax_invoice_code="W1")


@pytest.fixture
def bank(accountant):
    return banking.create_account(
        accountant,
        code="com-cur",
        kind="current",
        name="Commercial Bank current",
        bank_name="Commercial Bank",
        account_number="1000234567",
        ledger_account=chart.create_account(
            accountant,
            name="Commercial Bank current",
            account_type="bank",
            detail_type=DetailType.objects.get(name="Current account"),
            number="1030",
        ).pk,
    )


@pytest.fixture
def mailbox():
    MailAccount.objects.update_or_create(
        pk=1,
        defaults={
            "from_name": "SML Engineers Finance",
            "from_address": "finance@smlengineers.lk",
            "host": "smtp.hostinger.com",
        },
    )


def shafts():
    return QuoteLine(
        description="Drive shaft, EN8",
        drawing_no="DS-114",
        quantity="50",
        unit_price="2315.00",
        tax_code=TaxCode.objects.get(code="VAT-SSCL"),
    )


@pytest.fixture
def order(executive, director):
    """50 shafts at 2,315.00 for Lanka Tiles PLC (30 days' terms)."""
    return base.make_order(executive, director, shafts())


@pytest.fixture
def overdue(order, stores, accountant):
    """20 shafts invoiced 45 days ago, so due 15 days ago and overdue; 30 more delivered and
    waiting to be invoiced."""
    first = base.deliver(stores, order, "20")
    base.deliver(stores, order, "30")
    draft = invoices.create(accountant, order, [first])
    invoices.save(accountant, draft, invoices.Header(invoice_date=TODAY - timedelta(days=45)))
    return invoices.issue(accountant, draft)


def pay(cashier, accountant, bank, invoice, amount):
    made = receipts.record(
        cashier,
        customer=invoice.customer,
        method="transfer",
        account=bank,
        amount=amount,
        receipt_date=TODAY,
        reference="CEFT 5501",
        allocations=[Allocation(invoice, amount)],
    )
    return receipts.approve(accountant, made)


def money(value) -> str:
    return f"{value:.2f}"


# --- Aging and statements ----------------------------------------------------------------------


def test_aging_by_days_past_due_next_to_the_ledger(overdue, cashier, accountant, bank):
    pay(cashier, accountant, bank, overdue, "10000.00")
    left = overdue.total_amount - D("10000.00")
    (row,) = receivables.aging(accountant, TODAY)
    assert (row["code"], row["current"], row["d30"], row["total"], row["ledger"]) == (
        overdue.customer.code,
        "0.00",
        money(left),
        money(left),
        money(left),
    )
    # Twenty days ago the invoice was not yet due and nothing had been paid.
    (before,) = receivables.aging(accountant, TODAY - timedelta(days=20))
    assert (before["current"], before["d30"], before["ledger"]) == (
        money(overdue.total_amount),
        "0.00",
        money(overdue.total_amount),
    )
    assert receivables.aging(accountant, TODAY - timedelta(days=50)) == []


def test_the_statement_is_the_customer_s_ledger_with_a_running_balance(
    overdue, cashier, accountant, bank
):
    customer = overdue.customer
    receipt = pay(cashier, accountant, bank, overdue, "10000.00")
    st = receivables.statement(accountant, customer, TODAY - timedelta(days=60), TODAY)
    assert st.opening == 0
    assert [(x["reference"], x["debit"], x["credit"], x["balance"]) for x in st.lines] == [
        (overdue.number, overdue.total_amount, 0, overdue.total_amount),
        (receipt.number, 0, D("10000.00"), overdue.total_amount - D("10000.00")),
    ]
    assert st.closing == st.overdue == overdue.total_amount - D("10000.00")
    assert st.buckets["d30"] == st.closing
    later = receivables.statement(accountant, customer, TODAY - timedelta(days=10), TODAY)
    assert later.opening == overdue.total_amount and len(later.lines) == 1
    assert statement_printing.render(st).startswith(b"%PDF")
    with pytest.raises(SalesError, match="before its start"):
        receivables.statement(accountant, customer, TODAY, TODAY - timedelta(days=1))


# --- Credit control ------------------------------------------------------------------------------


def test_an_overdue_invoice_stops_the_next_one_until_the_director_allows_it(
    overdue, order, accountant, director
):
    draft = invoices.create(accountant, order)  # the 30 shafts waiting
    with pytest.raises(SalesError, match="Credit hold: Lanka Tiles PLC has 1 overdue invoice"):
        invoices.issue(accountant, draft)
    draft.refresh_from_db()
    assert (draft.status, draft.number, draft.journal_entry) == ("draft", "", None)
    hold = CreditHold.objects.get()
    assert (hold.document_type, hold.document_id, hold.status, hold.requested_by) == (
        "tax_invoice",
        draft.pk,
        "waiting",
        accountant,
    )
    assert (hold.overdue_lkr, hold.amount_lkr) == (overdue.total_amount, draft.total_amount)
    assert Notification.objects.filter(user=director, event="credit_hold_waiting").exists()
    with pytest.raises(SalesError, match="Credit hold"):
        invoices.issue(accountant, draft)  # tried again: the same hold, brought up to date
    assert CreditHold.objects.count() == 1

    with pytest.raises(SalesError, match="Only the Director"):
        receivables.allow(accountant, hold, "Customer promised")
    with pytest.raises(SalesError, match="Write why"):
        receivables.allow(director, hold, "  ")
    hold = receivables.allow(director, hold, "Paying on Friday, agreed by phone")
    assert (hold.status, hold.decided_by) == ("allowed", director)
    assert Notification.objects.filter(user=accountant, event="credit_hold_allowed").exists()
    assert invoices.issue(accountant, draft).status == "issued"
    with pytest.raises(SalesError, match="already been allowed"):
        receivables.allow(director, hold, "again")


def order_for(executive, director, customer):
    """A draft sales order of 50 shafts for an existing customer, ready to confirm."""
    q = services.save(
        executive,
        None,
        customer=customer,
        division=Division.objects.get(code="WS"),
        lines=[shafts()],
    )
    workflow.submit(executive, q)
    workflow.approve(director, q)
    q = workflow.record_outcome(executive, q, accepted=True, reason="price")
    o = orders.from_quotation(executive, q)
    orders.save(
        executive,
        o,
        customer_po="AB/PO/77",
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
    return o


def test_over_the_credit_limit_stops_the_sales_order(executive, director):
    customer = customers.create_customer(executive, {"name": "Abans PLC"}, confirmed=True)
    Customer.objects.filter(pk=customer.pk).update(credit_limit=D("100000.00"))
    customer.refresh_from_db()
    draft = order_for(executive, director, customer)
    draft.refresh_from_db()
    with pytest.raises(SalesError, match="over its credit limit of LKR 100,000.00"):
        orders.confirm(executive, draft)
    hold = CreditHold.objects.get()
    assert (hold.document_type, hold.exposure_lkr, hold.credit_limit) == (
        "sales_order",
        draft.total_lkr,
        D("100000.00"),
    )
    receivables.allow(director, hold, "Long-standing customer, cheque on the way")
    assert orders.confirm(executive, draft).status == "open"
    # Allowed holds are a record for good.
    with pytest.raises(DatabaseError), transaction.atomic():
        CreditHold.objects.filter(pk=hold.pk).update(note="changed")
    with pytest.raises(DatabaseError), transaction.atomic():
        CreditHold.objects.filter(pk=hold.pk).delete()


def test_within_the_limit_nothing_is_stopped(executive, director):
    customer = customers.create_customer(executive, {"name": "Abans PLC"}, confirmed=True)
    Customer.objects.filter(pk=customer.pk).update(credit_limit=D("500000.00"))
    customer.refresh_from_db()
    assert orders.confirm(executive, order_for(executive, director, customer)).status == "open"
    assert not CreditHold.objects.exists()
    reasons, figures = receivables.check(customer, D("500000.01"))
    assert reasons and figures.owed == 0


# --- Reminders ------------------------------------------------------------------------------------


def test_reminders_go_while_invoices_are_overdue_and_stop_when_paid(
    overdue, accountant, cashier, bank, mailbox
):
    customer = overdue.customer
    with pytest.raises(SalesError, match="no email address"):
        receivables.set_reminders(accountant, customer, is_on=True, every_days=7)
    Customer.objects.filter(pk=customer.pk).update(email="accounts@lankatiles.lk")
    customer.refresh_from_db()
    with pytest.raises(SalesError, match="The Accountant sets"):
        receivables.set_reminders(cashier, customer, is_on=True, every_days=7)
    with pytest.raises(SalesError, match="1 to 90 days"):
        receivables.set_reminders(accountant, customer, is_on=True, every_days=0)
    receivables.set_reminders(accountant, customer, is_on=True, every_days=7)

    assert receivables.send_reminders(TODAY) == 1
    (message,) = mail.outbox
    assert message.to == ["accounts@lankatiles.lk"]
    assert message.attachments[0][0] == f"Statement-{customer.code}-{TODAY:%Y-%m-%d}.pdf"
    sent = ReminderSent.objects.get()
    assert (sent.overdue_lkr, sent.email.sent_by) == (overdue.total_amount, accountant)
    assert receivables.send_reminders(TODAY) == 0  # once a day
    assert receivables.send_reminders(TODAY + timedelta(days=6)) == 0  # every 7 days
    assert receivables.send_reminders(TODAY + timedelta(days=7)) == 1

    pay(cashier, accountant, bank, overdue, f"{overdue.total_amount:.2f}")
    assert receivables.send_reminders(TODAY + timedelta(days=14)) == 0  # paid: they stop
    with pytest.raises(DatabaseError), transaction.atomic():
        ReminderSent.objects.all().delete()


def test_no_reminders_without_the_mailbox(overdue, accountant):
    Customer.objects.filter(pk=overdue.customer_id).update(email="accounts@lankatiles.lk")
    receivables.set_reminders(
        accountant, Customer.objects.get(pk=overdue.customer_id), is_on=True, every_days=7
    )
    assert receivables.send_reminders(TODAY) == 0
    assert not ReminderSent.objects.exists()


# --- API ---------------------------------------------------------------------------------------


def test_the_screens_api(overdue, order, accountant, director, stores, mailbox):
    customer = overdue.customer
    Customer.objects.filter(pk=customer.pk).update(email="accounts@lankatiles.lk")
    client = as_user(accountant)
    aging = client.get("/api/v1/receivables/aging/").json()
    assert aging["rows"][0]["d30"] == money(overdue.total_amount)
    assert client.get("/api/v1/receivables/aging/?export=xlsx").status_code == 200
    assert as_user(stores).get("/api/v1/receivables/aging/").status_code == 403

    path = f"/api/v1/receivables/statements/{customer.pk}/"
    body = client.get(f"{path}?from={TODAY - timedelta(days=60)}&to={TODAY}").json()
    assert body["lines"][0]["reference"] == overdue.number
    assert body["closing"] == money(overdue.total_amount)
    assert body["credit"]["on_hold"] is True and body["can_email"] is True
    assert body["items"][0]["days_overdue"] == 15
    pdf = client.get(f"{path}?export=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get(f"{path}?export=xlsx").status_code == 200

    draft = client.get(f"{path}email/").json()
    assert draft["to"] == ["accounts@lankatiles.lk"]
    sent = client.post(
        f"{path}email/",
        {"to": draft["to"], "subject": draft["subject"], "body": draft["body"]},
        format="json",
    )
    assert sent.status_code == 200 and sent.json()["emails"][0]["status"] == "sent"
    plan = client.put(f"{path}reminders/", {"is_on": True, "every_days": 14}, format="json")
    assert plan.status_code == 200 and plan.json()["every_days"] == 14

    waiting = invoices.create(accountant, order)
    refused = client.post(f"/api/v1/tax-invoices/{waiting.pk}/issue/")
    assert refused.status_code == 400 and "Credit hold" in refused.json()["detail"]
    (row,) = client.get("/api/v1/credit-holds/?status=waiting").json()
    assert row["can_allow"] is False and row["link"] == f"/tax-invoices/{waiting.pk}"
    boss = as_user(director)
    assert boss.get("/api/v1/credit-holds/").json()[0]["can_allow"] is True
    allowed = boss.post(f"/api/v1/credit-holds/{row['id']}/allow/", {"note": "OK"}, format="json")
    assert allowed.status_code == 200 and allowed.json()["status"] == "allowed"
    assert client.post(f"/api/v1/tax-invoices/{waiting.pk}/issue/").status_code == 200
