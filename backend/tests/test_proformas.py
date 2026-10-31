"""Proforma invoices and the packing list (backlog P15-08, spec 5.2, 5.5)."""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest
from django.core import mail
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import services as chart
from apps.accounting import taxes
from apps.accounting.models import DetailType, JournalEntry, TaxCode, TaxComponent
from apps.core import document_email
from apps.core.models import Division
from apps.masters import banking, customers
from apps.sales import advances, proforma_email, proforma_printing, proformas, services, workflow
from apps.sales.models import ProformaInvoice, ProformaLine, Quotation
from apps.sales.proformas import LineInput
from apps.sales.services import BreakInput, SalesError
from apps.sales.services import LineInput as QuoteLine

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
P = ProformaInvoice.Status


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def rhino(executive):
    customer = customers.create_customer(
        executive,
        {"name": "Rhino Roofing Products Ltd", "billing_address": "No 30, Minuwangoda Rd, Ekala"},
    )
    customers.add_contact(executive, customer, {"name": "Sunil", "email": "sunil@rhino.lk"})
    return customer


@pytest.fixture
def vat_sscl(accountant):
    start = TODAY - timedelta(days=30)
    for code, rate in (("VAT", "18"), ("SSCL", "2.5")):
        taxes.add_rate(
            accountant, TaxComponent.objects.get(code=code), effective_from=start, rate=rate
        )
    return TaxCode.objects.get(code="VAT-SSCL")


@pytest.fixture
def bank(accountant):
    ledger = chart.create_account(
        accountant,
        name="Commercial Bank current",
        account_type="bank",
        detail_type=DetailType.objects.get(name="Current account"),
        number="1030",
    )
    return banking.create_account(
        accountant,
        code="com-cur",
        kind="current",
        name="SML Engineers & Manufacturers (Pvt) Ltd",
        bank_name="Commercial Bank",
        branch="Seeduwa",
        account_number="1000234567",
        ledger_account=ledger.pk,
    )


def accepted(executive, director, customer, *lines, **values):
    q = services.save(
        executive,
        None,
        customer=customer,
        division=Division.objects.get(code="IM"),
        lines=list(lines),
        **values,
    )
    workflow.submit(executive, q)
    workflow.approve(director, q)
    return workflow.record_outcome(executive, q, accepted=True, reason="price")


@pytest.fixture
def won(executive, director, rhino, vat_sscl):
    """Clips at 1,500 each for 10, 1,200 for 50; and the mould, 3% off, as on the sample."""
    return accepted(
        executive,
        director,
        rhino,
        QuoteLine(
            description="Clip, PP",
            quantity="10",
            unit_price="1500",
            tax_code=vat_sscl,
            breaks=[BreakInput("50", "1200")],
        ),
        QuoteLine(
            description='Plastic injection mould for "CLIP", 32 cavities',
            quantity="1",
            unit_price="550000",
            tax_code=vat_sscl,
            is_tooling=True,
        ),
        discount_pct="3",
        payment_terms="Purchase order with 50% advance; balance on delivery",
        incoterm="EXW",
    )


@pytest.fixture
def draft(executive, won):
    return proformas.create(executive, won)


def lines_of(proforma, changes=None):
    """The proforma's lines as input, with changes by line number."""
    rows = []
    for line in proforma.lines.all():
        values = {"quotation_line": line.quotation_line, "quantity": line.quantity}
        values |= (changes or {}).get(line.line_no, {})
        rows.append(LineInput(**values))
    return rows


# --- Making a proforma from an accepted quotation --------------------------------------


def test_a_proforma_is_made_from_an_accepted_quotation(draft, won):
    assert draft.number == f"PI{TODAY:%y%m%d}-01"  # the owner's old style
    assert (draft.status, draft.quotation, draft.customer) == (P.DRAFT, won, won.customer)
    assert draft.contact.name == "Sunil"
    assert (draft.discount_pct, draft.payment_terms, draft.incoterm) == (
        Decimal("3.00"),
        won.payment_terms,
        "EXW",
    )
    clip, mould = draft.lines.all()
    assert (clip.quantity, clip.unit_price) == (Decimal("10.000"), Decimal("1500.00"))
    assert mould.is_tooling
    # The same figures as the quotation.
    assert (draft.subtotal, draft.total_amount) == (won.subtotal, won.total_amount)


def test_a_proforma_records_no_sale(draft, executive):
    proformas.issue(executive, draft)
    assert JournalEntry.objects.count() == 0  # spec 5.2: no sale, no receivable


def test_only_an_accepted_quotation_makes_a_proforma(executive, director, rhino):
    q = services.save(
        executive,
        None,
        customer=rhino,
        division=Division.objects.get(code="WS"),
        lines=[QuoteLine(description="Shaft", quantity="1", unit_price="100")],
    )
    with pytest.raises(SalesError, match="mark the quotation won first"):
        proformas.create(executive, q)
    workflow.submit(executive, q)
    workflow.approve(director, q)
    with pytest.raises(SalesError, match="mark the quotation won first"):
        proformas.create(executive, q)


@pytest.mark.parametrize(
    "quantity, price",
    [("60", "1200.00"), ("50", "1200.00"), ("20", "1500.00"), ("5", "1500.00")],
)
def test_the_price_comes_from_the_quotation_for_the_quantity(draft, executive, quantity, price):
    changed = proformas.save(executive, draft, lines=lines_of(draft, {1: {"quantity": quantity}}))
    assert changed.lines.get(line_no=1).unit_price == Decimal(price)


# --- Changing a draft, packing list ------------------------------------------------------


def test_terms_bank_advance_and_packing(draft, executive, bank):
    packing = {
        "cartons": "3",
        "qty_per_carton": "20",
        "net_weight_kg": "30",
        "gross_weight_kg": "33.5",
        "carton_length_cm": "40",
        "carton_width_cm": "30",
        "carton_height_cm": "25",
    }
    changed = proformas.save(
        executive,
        draft,
        lines=lines_of(draft, {1: {"quantity": "60", **packing}}),
        customer_po="RR/PO/4512",
        port_of_loading="Colombo",
        bank_account=bank,
        advance_pct="50",
    )
    half = (changed.total_amount * Decimal("0.5")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    assert changed.advance_amount == half
    clip = changed.lines.get(line_no=1)
    assert (clip.cartons, clip.gross_weight_kg) == (3, Decimal("33.500"))
    assert proformas.volume_m3(clip) == Decimal("0.090")  # 3 × 40 × 30 × 25 cm
    totals = proformas.packing_totals(changed)
    assert (totals["cartons"], totals["net_weight_kg"], totals["volume_m3"]) == (
        3,
        Decimal("30.000"),
        Decimal("0.090"),
    )


@pytest.mark.parametrize(
    "change, why",
    [
        ({1: {"net_weight_kg": "30", "gross_weight_kg": "29"}}, "gross weight cannot be less"),
        ({1: {"quantity": "0"}}, "more than 0"),
        ({1: {"cartons": "2.5"}}, "Line 1"),
    ],
)
def test_wrong_lines_are_refused(draft, executive, change, why):
    with pytest.raises(SalesError, match=why):
        proformas.save(executive, draft, lines=lines_of(draft, change))


def test_lines_come_only_from_the_quotation_and_once(draft, executive, director, rhino):
    other = accepted(
        executive,
        director,
        rhino,
        QuoteLine(description="Other", quantity="1", unit_price="10"),
    )
    stranger = other.lines.get()
    with pytest.raises(SalesError, match="choose a line of the quotation"):
        proformas.save(executive, draft, lines=[LineInput(stranger, "1")])
    twice = lines_of(draft) + lines_of(draft)[:1]
    with pytest.raises(SalesError, match="once"):
        proformas.save(executive, draft, lines=twice)


def test_only_the_creator_changes_a_draft(draft):
    manager = person("salesmanager@sml.lk", "sales_manager", all_divisions=True)
    with pytest.raises(SalesError, match="Only the person who made"):
        proformas.save(manager, draft, lines=lines_of(draft))


# --- Issued: never changed; cancelled with a reason --------------------------------------


def test_an_issued_proforma_never_changes(draft, executive):
    issued = proformas.issue(executive, draft)
    assert issued.status == P.ISSUED and issued.issued_at is not None
    with pytest.raises(SalesError, match="Only the person who made a draft"):
        proformas.save(executive, issued, lines=lines_of(issued))
    with pytest.raises(DatabaseError, match="cannot be changed"), transaction.atomic():
        ProformaInvoice.objects.filter(pk=issued.pk).update(total_amount=Decimal("1.00"))
    with pytest.raises(DatabaseError, match="cannot change"), transaction.atomic():
        ProformaLine.objects.filter(proforma=issued).update(quantity=Decimal("1"))
    # Deleting is refused too (its lines refuse first).
    with pytest.raises(DatabaseError, match="cannot"), transaction.atomic():
        ProformaInvoice.objects.filter(pk=issued.pk).delete()


def test_cancelling_needs_a_reason_and_no_advance_received(draft, executive, accountant, bank):
    issued = proformas.issue(executive, draft)
    with pytest.raises(SalesError, match="Give a reason"):
        proformas.cancel(executive, issued, "")
    cashier = person("cashier@sml.lk", "cashier", all_divisions=True)
    advance = advances.record(
        cashier,
        customer=issued.customer,
        account=bank,
        method="transfer",
        amount="300000",
        receipt_date=TODAY,
        reference="CEFT 1",
        proforma=issued,
    )
    assert (advance.proforma, advance.quotation) == (issued, issued.quotation)
    advances.approve(accountant, advance)
    with pytest.raises(SalesError, match="advance has been received"):
        proformas.cancel(executive, issued, "Customer changed the order")


def test_a_cancelled_proforma_stays_cancelled(draft, executive):
    issued = proformas.issue(executive, draft)
    cancelled = proformas.cancel(executive, issued, "Customer changed the order")
    assert (cancelled.status, cancelled.cancel_reason) == (
        P.CANCELLED,
        "Customer changed the order",
    )
    with pytest.raises(DatabaseError, match="cancelled for good"), transaction.atomic():
        ProformaInvoice.objects.filter(pk=cancelled.pk).update(status=P.ISSUED)


def test_an_advance_is_against_an_issued_proforma(draft, bank):
    cashier = person("cashier@sml.lk", "cashier", all_divisions=True)
    with pytest.raises(SalesError, match="against an issued proforma"):
        advances.record(
            cashier,
            customer=draft.customer,
            account=bank,
            method="transfer",
            amount="1000",
            receipt_date=TODAY,
            reference="CEFT 2",
            proforma=draft,
        )


# --- Printed proforma and packing list; email --------------------------------------------


def text(proforma) -> bytes:
    pdf = proforma_printing.render(ProformaInvoice.objects.get(pk=proforma.pk), compress=False)
    return pdf.replace(b"\\(", b"(").replace(b"\\)", b")")


def test_the_printed_proforma_and_its_packing_list(draft, executive, bank):
    proformas.save(
        executive,
        draft,
        lines=lines_of(
            draft, {1: {"cartons": "1", "net_weight_kg": "2", "gross_weight_kg": "2.4"}}
        ),
        bank_account=bank,
        advance_pct="50",
        customer_po="RR/PO/4512",
    )
    pdf = text(draft)
    assert b"NOT ISSUED" in pdf  # a draft
    proformas.issue(executive, draft)
    pdf = text(draft)
    for expected in (
        b"PROFORMA INVOICE",
        f"Our Ref: {draft.number}".encode(),
        b"Your PO: RR/PO/4512",
        b"Rhino Roofing Products Ltd",
        b"Discount",
        b"-16,950.00",  # 3% of 565,000
        b"Advance Payment (50%)",
        b"Balance Payment",
        b"Bank details for payment",
        b"1000234567",
        b"Managing Director",
        b"EXCELLENCE THROUGH EXPERTISE",
        b"PACKING LIST",
        b"2.4",
    ):
        assert expected in pdf, expected
    assert b"NOT ISSUED" not in pdf and b"SVAT" not in pdf


def test_an_issued_proforma_is_emailed_with_its_pdf(draft, executive):
    admin = person("admin@sml.lk", "system_admin", all_divisions=True)
    document_email.update_account(
        admin,
        {
            "from_address": "sales@smlengineers.lk",
            "host": "smtp.hostinger.com",
            "port": 465,
            "security": "ssl",
            "username": "sales@smlengineers.lk",
            "password": "Mailbox-Secret-1",
        },
        reason="go-live",
    )
    with pytest.raises(SalesError, match="Only an issued proforma"):
        proforma_email.draft(executive, draft)
    issued = proformas.issue(executive, draft)
    message = proforma_email.draft(executive, issued)
    assert message["to"] == ["sunil@rhino.lk"]
    record = proforma_email.send(
        executive, issued, to=message["to"], subject=message["subject"], body=message["body"]
    )
    assert record.status == "sent"
    (sent,) = mail.outbox
    assert sent.attachments[0][0] == f"Proforma-{issued.number}.pdf"


# --- Through the API ---------------------------------------------------------------------


def test_the_api_makes_changes_issues_and_prints(executive, won, bank):
    client = as_user(executive)
    made = client.post("/api/v1/proformas/", {"quotation": won.pk}, format="json")
    assert made.status_code == 201, made.json()
    body = made.json()
    url = f"/api/v1/proformas/{body['id']}/"
    lines = [
        {"quotation_line": row["quotation_line"], "quantity": row["quantity"], "cartons": "2"}
        for row in body["lines"]
    ]
    changed = client.put(
        url,
        {
            "lines": lines,
            "bank_account": bank.pk,
            "advance_pct": "50",
            "port_of_loading": "Colombo",
        },
        format="json",
    )
    assert changed.status_code == 200, changed.json()
    assert changed.json()["packing_totals"]["cartons"] == "4"
    assert changed.json()["bank_account"]["code"] == "COM-CUR"
    issued = client.post(f"{url}issue/", {}, format="json").json()
    assert issued["status"] == "issued" and issued["can_edit"] is False
    pdf = client.get(f"{url}pdf/")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    other = person("sales2@sml.lk", "sales_executive", all_divisions=True)
    assert as_user(other).get(url).status_code == 404
    listing = as_user(person("acc@sml.lk", "accountant", all_divisions=True)).get(
        "/api/v1/proformas/"
    )
    assert [row["number"] for row in listing.json()] == [body["number"]]


def test_the_quotation_must_be_accepted_through_the_api_too(executive, rhino):
    q = services.save(
        executive,
        None,
        customer=rhino,
        division=Division.objects.get(code="WS"),
        lines=[QuoteLine(description="Shaft", quantity="1", unit_price="100")],
    )
    answer = as_user(executive).post("/api/v1/proformas/", {"quotation": q.pk}, format="json")
    assert answer.status_code == 400 and "won first" in answer.json()["detail"]
    assert Quotation.objects.get(pk=q.pk).proformas.count() == 0
