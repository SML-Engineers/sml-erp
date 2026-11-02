"""Tax invoices (backlog P2-05, spec 6.1)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import Account, TaxCode, TaxComponent
from apps.core.models import Company, Division
from apps.masters import customers
from apps.sales import deliveries, invoice_printing, invoices, orders, services, words, workflow
from apps.sales.deliveries import LineInput as DeliveryLine
from apps.sales.models import (
    DeliveryNote,
    SalesOrder,
    TaxInvoice,
    TaxInvoiceLine,
    TaxInvoiceTax,
)
from apps.sales.orders import Delivery
from apps.sales.orders import LineInput as OrderLine
from apps.sales.services import LineInput as QuoteLine
from apps.sales.services import SalesError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
D = Decimal
GO_LIVE = date(2024, 1, 1)
NUMBER = f"{TODAY:%y}{TODAY:%b}".upper() + "_W1_"


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def stores():
    return person("stores@sml.lk", "store_supervisor", all_divisions=True)


@pytest.fixture(autouse=True)
def setup(accountant):
    """The Accountant's rates (spec 6.1: SSCL 2.125%, VAT 18%), the company's TIN and the
    Workshop's tax invoice code W1."""
    for code, rate in (("SSCL", "2.125"), ("VAT", "18")):
        component = TaxComponent.objects.get(code=code)
        taxes.add_rate(accountant, component, effective_from=GO_LIVE, rate=rate)
    Company.objects.filter(pk=1).update(
        name="SML Engineers (Pvt) Ltd",
        tin="134567890",
        address="12 Factory Road, Ja-Ela",
        phone="011 223 4455",
        email="accounts@smlengineers.com",
    )
    Division.objects.filter(code="WS").update(tax_invoice_code="W1")


def make_order(executive, director, *lines, discount=None):
    customer = customers.create_customer(
        executive,
        {
            "name": "Lanka Tiles PLC",
            "billing_address": "215 Nawala Road, Nugegoda",
            "delivery_address": "Factory, Ranala",
            "tin": "114455667",
            "payment_terms_days": 30,
        },
        confirmed=True,
    )
    q = services.save(
        executive,
        None,
        customer=customer,
        division=Division.objects.get(code="WS"),
        lines=list(lines),
    )
    workflow.submit(executive, q)
    workflow.approve(director, q)
    q = workflow.record_outcome(executive, q, accepted=True, reason="price")
    o = orders.from_quotation(executive, q)
    orders.save(
        executive,
        o,
        customer_po="LT/PO/1201",
        payment_terms="Due on receipt",
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


@pytest.fixture
def order(executive, director):
    """50 shafts at 2,315.00 = 115,750.00, standard VAT and SSCL (the spec's example)."""
    return make_order(
        executive,
        director,
        QuoteLine(
            description="Drive shaft, EN8",
            drawing_no="DS-114",
            quantity="50",
            unit_price="2315.00",
            tax_code=TaxCode.objects.get(code="VAT-SSCL"),
        ),
    )


def deliver(stores, order, *quantities):
    lines = [
        DeliveryLine(line, q)
        for line, q in zip(order.lines.order_by("line_no"), quantities, strict=False)
        if q
    ]
    return deliveries.issue(stores, deliveries.create(stores, order, lines=lines))


def acc(number):
    return Account.objects.get(number=number)


# --- The spec's example ------------------------------------------------------------------------


def test_the_invoice_of_the_spec_s_example(order, stores, executive, accountant):
    note = deliver(stores, order, "50")
    draft = invoices.create(executive, order)  # Sales prepare it
    assert (draft.status, draft.number) == ("draft", "")
    assert (draft.supply_date, draft.due_date) == (note.delivery_date, TODAY + timedelta(days=30))
    assert (draft.terms, draft.place_of_supply) == ("Due on receipt", "Factory, Ranala")
    assert [(t.label, t.rate, t.amount) for t in draft.taxes.all()] == [
        ("SSCL", D("2.1250"), D("2459.69")),
        ("VAT", D("18.0000"), D("21277.74")),
    ]
    assert draft.total_amount == D("139487.43")
    invoice = invoices.issue(accountant, draft)
    assert invoice.number == f"{NUMBER}01"
    assert (invoice.supplier_tin, invoice.customer_tin) == ("134567890", "114455667")
    assert invoice.amount_in_words == (
        "Rupees One Hundred Thirty Nine Thousand Four Hundred Eighty Seven and Cents Forty "
        "Three Only"
    )
    entry = invoice.journal_entry
    assert (entry.source_type, entry.source_id, entry.entry_date) == (
        "tax_invoice",
        invoice.number,
        TODAY,
    )
    lines = [
        (x.account.number, x.debit, x.credit, x.division.code, x.customer_id)
        for x in entry.lines.order_by("line_no")
    ]
    assert lines == [
        ("1100", D("139487.43"), 0, "WS", order.customer_id),
        ("4010", 0, D("115750.00"), "WS", None),
        ("2110", 0, D("2459.69"), "WS", None),
        ("2100", 0, D("21277.74"), "WS", None),
    ]
    order.refresh_from_db()
    assert order.status == SalesOrder.Status.COMPLETED  # delivered and fully invoiced


def test_the_number_restarts_each_month_per_division_and_drafts_leave_no_gaps(
    order, stores, accountant
):
    first = deliver(stores, order, "20")
    deliver(stores, order, "30")
    one = invoices.create(accountant, order, [first])
    assert [x.quantity for x in one.lines.all()] == [D("20.000")]
    two = invoices.create(accountant, order)  # what is left: the second note
    assert [x.quantity for x in two.lines.all()] == [D("30.000")]
    invoices.delete(accountant, one)
    three = invoices.create(accountant, order)
    assert invoices.issue(accountant, two).number == f"{NUMBER}01"
    assert invoices.issue(accountant, three).number == f"{NUMBER}02"
    with pytest.raises(SalesError, match="no delivered quantities waiting"):
        invoices.create(accountant, order)


def test_tooling_goes_to_the_tooling_account(executive, director, stores, accountant):
    o = make_order(
        executive,
        director,
        QuoteLine(description="Bracket", quantity="10", unit_price="100.00"),
        QuoteLine(description="Press tool", quantity="1", unit_price="50000.00", is_tooling=True),
    )
    deliver(stores, o, "10", "1")
    invoice = invoices.issue(accountant, invoices.create(accountant, o))
    credits = {x.account.number: x.credit for x in invoice.journal_entry.lines.all() if x.credit}
    assert credits == {"4010": D("1000.00"), "4030": D("50000.00")}  # no tax code, no tax
    assert invoice.total_amount == D("51000.00")


# --- Refused ------------------------------------------------------------------------------------


def test_what_issuing_needs(order, stores, accountant):
    deliver(stores, order, "50")
    draft = invoices.create(accountant, order)
    Division.objects.filter(code="WS").update(tax_invoice_code="")
    with pytest.raises(SalesError, match="no tax invoice code"):
        invoices.issue(accountant, draft)
    Division.objects.filter(code="WS").update(tax_invoice_code="W1")
    Company.objects.filter(pk=1).update(tin="")
    with pytest.raises(SalesError, match="company's TIN"):
        invoices.issue(accountant, draft)
    Company.objects.filter(pk=1).update(tin="134567890")
    with pytest.raises(SalesError, match="cannot be in the future"):
        invoices.save(accountant, draft, invoices.Header(invoice_date=TODAY + timedelta(days=1)))
    assert not TaxInvoice.objects.exclude(number="").exists()  # nothing numbered by mistake
    invoices.issue(accountant, draft)


def test_an_issued_invoice_never_changes(order, stores, accountant):
    note = deliver(stores, order, "50")
    invoice = invoices.issue(accountant, invoices.create(accountant, order))
    with pytest.raises(SalesError, match="Only a draft"):
        invoices.save(accountant, invoice, invoices.Header(terms="30 days"))
    with pytest.raises(SalesError, match="Only a draft"):
        invoices.delete(accountant, invoice)
    for attempt, why in (
        (lambda: TaxInvoice.objects.filter(pk=invoice.pk).update(terms="x"), "never changed"),
        (lambda: TaxInvoiceLine.objects.filter(invoice=invoice).update(rate="1"), "never change"),
        (lambda: TaxInvoiceTax.objects.filter(invoice=invoice).delete(), "never change"),
    ):
        with pytest.raises(DatabaseError, match=why):
            with transaction.atomic():
                attempt()
    with pytest.raises(DatabaseError, match="cannot be deleted"):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM sales_taxinvoice WHERE id = %s", [invoice.pk])
    # Its delivery note can no longer be cancelled: a credit note corrects the invoice.
    manager = person("salesmgr@sml.lk", "sales_manager", all_divisions=True)
    with pytest.raises(SalesError, match="on a tax invoice"):
        deliveries.cancel(manager, note, "wrong")
    with pytest.raises(DatabaseError, match="has been invoiced"):
        with transaction.atomic():
            DeliveryNote.objects.filter(pk=note.pk).update(status="cancelled", cancel_reason="x")


def test_sales_the_director_and_the_accountant_issue(executive, director, stores, accountant):
    """Owner's decision of 3 Nov 2026."""
    issued = []
    for who in (executive, director, accountant):
        o = make_order(
            executive,
            director,
            QuoteLine(description="Bush", quantity="2", unit_price="500.00"),
        )
        deliver(stores, o, "2")
        draft = invoices.create(executive, o)
        assert invoices.can_issue(who, draft)
        issued.append(invoices.issue(who, draft).number)
    assert issued == [f"{NUMBER}01", f"{NUMBER}02", f"{NUMBER}03"]
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert not invoices.can_issue_any(clerk)
    assert not invoices.can_issue_any(stores)


def test_who_prepares_and_sees(order, stores, executive, accountant):
    deliver(stores, order, "50")
    other = person("sales2@sml.lk", "sales_executive", all_divisions=True)
    with pytest.raises(SalesError, match="no delivered quantities"):
        invoices.create(other, order)  # not their order
    with pytest.raises(SalesError, match="Only Sales or the Accountant"):
        invoices.create(stores, order)
    draft = invoices.create(executive, order)
    assert list(invoices.visible(accountant)) == [draft]
    assert not invoices.visible(other).exists()
    assert not invoices.visible(stores).exists()


def test_amounts_in_words():
    assert words.amount(D("0.50")) == "Rupees Zero and Cents Fifty Only"
    assert words.amount(D("1000000")) == "Rupees One Million Only"
    assert words.amount(D("2015.05")) == "Rupees Two Thousand Fifteen and Cents Five Only"


# --- Printing and API -------------------------------------------------------------------------


def test_the_printed_invoice(order, stores, accountant):
    deliver(stores, order, "50")
    draft = invoices.create(accountant, order)
    assert b"DRAFT" in invoice_printing.render(draft, compress=False)
    invoice = invoices.issue(accountant, draft)
    text = invoice_printing.render(invoice, compress=False)
    for expected in (
        "TAX INVOICE",
        invoice.number,
        "134567890",
        "114455667",
        f"{TODAY:%m/%d/%Y}",
        "DS-114",
        "LT/PO/1201",
        "115,750.00",
        "2.125%",
        "2,459.69",
        "21,277.74",
        "139,487.43",
        "Prepared By",
        "Checked By",
    ):
        assert expected.encode() in text, expected
    assert b"DRAFT" not in text


def test_the_api(order, stores, executive, accountant, director):
    deliver(stores, order, "50")
    client = as_user(executive)
    todo = client.get("/api/v1/tax-invoices/orders/").json()
    assert [(o["number"], len(o["delivery_notes"])) for o in todo] == [(order.number, 1)]
    made = client.post("/api/v1/tax-invoices/", {"order": order.pk}, format="json")
    assert made.status_code == 201, made.json()
    pk = made.json()["id"]
    assert made.json()["total_amount"] == "139487.43"
    assert made.json()["can_issue"] is True
    changed = client.put(
        f"/api/v1/tax-invoices/{pk}/", {"place_of_supply": "Ranala\nWarehouse 2"}, format="json"
    )
    assert changed.json()["place_of_supply"] == "Ranala, Warehouse 2"
    assert as_user(stores).post(f"/api/v1/tax-invoices/{pk}/issue/").status_code == 403
    issued = as_user(director).post(f"/api/v1/tax-invoices/{pk}/issue/")
    assert issued.status_code == 200, issued.json()
    assert issued.json()["number"] == f"{NUMBER}01"
    pdf = client.get(f"/api/v1/tax-invoices/{pk}/pdf/")
    assert pdf["Content-Type"] == "application/pdf"
    entry = issued.json()["journal_entry"]["id"]
    assert as_user(accountant).get(f"/api/v1/journal/{entry}/").json()["source_page"] == (
        f"/tax-invoices/{pk}"
    )
    detail = client.get(f"/api/v1/sales-orders/{order.pk}/").json()
    assert [i["number"] for i in detail["invoices"]] == [issued.json()["number"]]
    assert (
        as_user(person("qc@sml.lk", "qc_inspector")).get("/api/v1/tax-invoices/").status_code == 403
    )


def test_the_sales_accounts(accountant, executive):
    client = as_user(accountant)
    rows = {r["division"]["code"]: r for r in client.get("/api/v1/sales-accounts/").json()}
    assert rows["IM"]["account"]["number"] == "4020"
    assert rows["WS"]["tooling_account"]["number"] == "4030"
    body = {"division": "IM", "account": acc("4030").pk, "tooling_account": acc("4030").pk}
    assert as_user(executive).put("/api/v1/sales-accounts/", body, format="json").status_code == 403
    bad = {"division": "IM", "account": acc("1010").pk, "tooling_account": acc("4030").pk}
    assert client.put("/api/v1/sales-accounts/", bad, format="json").status_code == 400
    assert client.put("/api/v1/sales-accounts/", body, format="json").status_code == 200
