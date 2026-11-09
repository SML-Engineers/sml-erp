"""Printed quotation and email (backlog P15-07, spec 5.1, 3B)."""

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode, TaxComponent
from apps.core import document_email
from apps.core.models import Company, Division, SentEmail
from apps.masters import costing_rates, customers
from apps.masters import services as masters
from apps.masters.models import Section
from apps.sales import costing, printing, quotation_email, services, workflow
from apps.sales.costing import CostingInput, OperationInput
from apps.sales.models import Quotation
from apps.sales.services import BreakInput, LineInput, SalesError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


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
def aluflex(executive):
    customer = customers.create_customer(
        executive,
        {
            "name": "Aluflex Lanka (Pvt) Ltd",
            "billing_address": "No 588/A/12, Ranmuthugala Estate, Kadawatha",
        },
    )
    customers.add_contact(executive, customer, {"name": "Ruwani", "email": "ruwani@aluflex.lk"})
    return customer


@pytest.fixture
def vat_sscl(accountant):
    """SSCL 2.5% and VAT 18% in force, as on the owner's sample QL26061501."""
    start = TODAY - timedelta(days=30)
    for code, rate in (("VAT", "18"), ("SSCL", "2.5")):
        taxes.add_rate(
            accountant, TaxComponent.objects.get(code=code), effective_from=start, rate=rate
        )
    return TaxCode.objects.get(code="VAT-SSCL")


@pytest.fixture
def draft(executive, aluflex, vat_sscl):
    """The owner's sample: surface grinding of a cutting die, 1 set at LKR 11,800."""
    return services.save(
        executive,
        None,
        customer=aluflex,
        division=Division.objects.get(code="WS"),
        payment_terms="50% advance with the purchase order, balance on delivery",
        incoterm="EXW",
        lines=[
            LineInput(
                description="Surface grinding top surface of cutting die (1 set = 8 pcs)",
                quantity="1",
                unit_price="11800",
                tax_code=vat_sscl,
                drawing_no="AL-221",
                breaks=[BreakInput("5", "11000")],
            )
        ],
    )


@pytest.fixture
def approved(draft, executive, director):
    workflow.submit(executive, draft)
    return workflow.approve(director, draft)


@pytest.fixture
def mailbox():
    admin = person("admin@sml.lk", "system_admin", all_divisions=True)
    document_email.update_account(
        admin,
        {
            "from_name": "SML Engineers",
            "from_address": "sales@smlengineers.lk",
            "host": "smtp.hostinger.com",
            "port": 465,
            "security": "ssl",
            "username": "sales@smlengineers.lk",
            "password": "Mailbox-Secret-1",
        },
        reason="go-live",
    )


def text(quotation) -> bytes:
    """The PDF uncompressed, with PDF's escaped brackets put back, so the words it shows
    can be searched."""
    pdf = printing.render(Quotation.objects.get(pk=quotation.pk), compress=False)
    return pdf.replace(b"\\(", b"(").replace(b"\\)", b")")


# --- The printed quotation --------------------------------------------------------------


def test_the_quotation_prints_like_the_owners_sample(approved):
    Company.objects.filter(pk=1).update(
        name="SML Engineers & Manufacturers (Pvt) Ltd",
        address="195, Negambo Road, Ambalammulla, Seeduwa",
    )
    pdf = text(approved)
    assert pdf.startswith(b"%PDF")
    for expected in (
        b"SML ENGINEERS & MANUFACTURERS (PVT) LTD",
        b"QUOTATION",
        f"Our Ref: {approved.number}".encode(),
        b"Aluflex Lanka (Pvt) Ltd",
        b"11,800.00",
        b"SSCL",
        b"2.5%",
        b"295.00",  # SSCL 2.5% on 11,800
        b"12,095.00",  # subtotal
        b"VAT (18%)",
        b"2,177.10",  # VAT on 12,095
        b"14,272.10",  # total
        b"Drawing AL-221",
        b"For 5 pcs: LKR 11,000.00 each",
        b"EXW",
        b"07 Days",
        b"Managing Director",
        b"EXCELLENCE THROUGH EXPERTISE",
    ):
        assert expected in pdf, expected
    assert b"SVAT" not in pdf  # the scheme ended on 1 Oct 2025
    assert b"NOT APPROVED" not in pdf


def test_a_quotation_not_approved_prints_only_as_a_draft(draft, executive):
    assert b"NOT APPROVED" in text(draft)
    workflow.submit(executive, draft)
    assert b"NOT APPROVED" in text(draft)


def test_the_customers_copy_has_no_costing(approved, executive, accountant):
    """Costing figures never appear on the printed quotation."""
    Quotation.objects.filter(pk=approved.pk).update(status=Quotation.Status.DRAFT)
    q = Quotation.objects.get(pk=approved.pk)
    costing_rates.add_costing_rate(
        accountant,
        Division.objects.get(code="WS"),
        effective_from=TODAY,
        overhead_pct="17",
        margin_pct="23",
        setup_rate="1500",
    )
    grinder = masters.create_machine(
        code="M-SG-01", section=Section.objects.get(code="M-GRD"), name="Surface grinder"
    )
    masters.add_rate(grinder, effective_from=TODAY, rate="4321")
    costing.save(executive, q, 1, CostingInput(operations=[OperationInput(grinder, "97")]))
    figures = costing.results(q.lines.get().costing, q.lines.get(), q.exchange_rate)[0]
    # Only the words printed on the page: the file's own numbers (lengths, positions) may
    # contain any digits by chance.
    shown = b" ".join(re.findall(rb"\((.*?)\)\s*Tj", text(q)))
    assert b"QUOTATION" in shown.upper()
    for secret in ("4,321.00", "4321", "17%", "23%", f"{figures['cost']:,.2f}", "Overhead"):
        assert secret.encode() not in shown, secret


def test_an_export_quotation_shows_its_rate(executive, aluflex):
    from apps.masters import currencies
    from apps.masters.models import Currency

    currencies.set_rate(currency=Currency.objects.get(code="EUR"), on_date=TODAY, rate="325.40")
    q = services.save(
        executive,
        None,
        customer=aluflex,
        division=Division.objects.get(code="IM"),
        currency="EUR",
        lines=[LineInput(description="Cap", quantity="1000", unit_price="0.35")],
    )
    pdf = text(q)
    assert b"Unit Price" in pdf and b"EUR" in pdf
    assert b"1 EUR = LKR 325.4" in pdf


def test_anyone_who_sees_the_quotation_can_print_it(draft, accountant):
    answer = as_user(accountant).get(f"/api/v1/quotations/{draft.pk}/pdf/")
    assert answer.status_code == 200 and answer["Content-Type"] == "application/pdf"
    assert answer.content.startswith(b"%PDF")
    assert f'filename="Quotation-{draft.number}-Rev-0.pdf"' in answer["Content-Disposition"]


# --- Email ------------------------------------------------------------------------------


def test_only_an_approved_quotation_is_emailed(draft, executive, mailbox):
    with pytest.raises(SalesError, match="approved by the Director"):
        quotation_email.draft(executive, draft)
    with pytest.raises(SalesError, match="approved by the Director"):
        quotation_email.send(executive, draft, to=["ruwani@aluflex.lk"], subject="Q", body="Hi")
    assert mail.outbox == []


def test_emailing_sends_the_pdf_and_marks_it_sent(approved, executive, mailbox):
    message = quotation_email.draft(executive, approved)
    assert message["to"] == ["ruwani@aluflex.lk"]  # the main contact
    assert approved.number in message["subject"]
    record = quotation_email.send(
        executive,
        approved,
        to=message["to"],
        subject=message["subject"],
        body=message["body"],
    )
    assert record.status == SentEmail.Status.SENT
    (sent,) = mail.outbox
    name, content, mimetype = sent.attachments[0]
    assert (name, mimetype) == (f"Quotation-{approved.number}.pdf", "application/pdf")
    assert content.startswith(b"%PDF")
    approved.refresh_from_db()
    assert approved.status == Quotation.Status.SENT and approved.sent_by == executive
    assert quotation_email.history(approved)[0]["to"] == "ruwani@aluflex.lk"


def test_the_api_emails_only_for_the_creator_or_the_sales_manager(approved, mailbox, accountant):
    url = f"/api/v1/quotations/{approved.pk}/email/"
    assert as_user(accountant).get(url).status_code == 400
    manager = person("salesmanager@sml.lk", "sales_manager", all_divisions=True)
    client = as_user(manager)
    message = client.get(url).json()
    sent = client.post(
        url,
        {"to": message["to"], "subject": message["subject"], "body": message["body"]},
        format="json",
    )
    assert sent.status_code == 200, sent.json()
    body = sent.json()
    assert body["status"] == "sent" and body["emails"][0]["status"] == "sent"
    assert Decimal(body["total_amount"]) == Decimal("14272.10")
