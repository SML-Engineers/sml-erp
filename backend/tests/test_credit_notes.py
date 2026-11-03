"""Credit notes (backlog P2-06)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import journal, taxes
from apps.accounting.journal import Line
from apps.accounting.models import Account, TaxCode, TaxComponent
from apps.core import approvals
from apps.core.models import AccessOverride, Company, Division, Notification, User
from apps.sales import credit_note_printing, credit_notes, invoices
from apps.sales.credit_notes import LineInput
from apps.sales.models import CreditNote, CreditNoteLine
from apps.sales.services import LineInput as QuoteLine
from apps.sales.services import SalesError

from . import test_tax_invoices as base
from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
D = Decimal
NUMBER = f"CN{TODAY:%y%m%d}"


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
    for code, rate in (("SSCL", "2.125"), ("VAT", "18")):
        component = TaxComponent.objects.get(code=code)
        taxes.add_rate(accountant, component, effective_from=base.GO_LIVE, rate=rate)
    Company.objects.filter(pk=1).update(name="SML Engineers (Pvt) Ltd", tin="134567890")
    Division.objects.filter(code="WS").update(tax_invoice_code="W1")


@pytest.fixture
def invoice(executive, director, stores, accountant):
    """The spec's invoice: 50 shafts at 2,315.00 = 115,750.00, total 139,487.43."""
    order = base.make_order(
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
    base.deliver(stores, order, "50")
    return invoices.issue(accountant, invoices.create(executive, order))


def line(invoice, amount, quantity="0"):
    return [LineInput(invoice.lines.get(), amount, quantity)]


def price(user, invoice, amount, **values):
    values = {"kind": "price", "reason": "Agreed discount on late delivery"} | values
    return credit_notes.create(user, invoice, lines=line(invoice, amount), **values)


def grant(user, action, director, confirmed=True):
    AccessOverride.objects.create(
        user=user,
        action=action,
        effect=AccessOverride.Effect.GRANT,
        reason="Approves credit notes while the Director travels",
        is_sensitive=True,
        created_by=person("admin@sml.lk", "system_admin", all_divisions=True),
        confirmed_by=director if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
    )
    return fresh(user)


def fresh(user):
    """A user's access is worked out once per request; a new request sees a new grant."""
    return User.objects.get(pk=user.pk)


# --- The figures and the posting --------------------------------------------------------------


def test_a_price_correction_reverses_the_invoice_at_its_rates(invoice, executive, director):
    note = price(executive, invoice, "15750.00")
    assert (note.status, note.number) == ("draft", "")
    assert [(t.label, t.rate, t.amount) for t in note.taxes.all()] == [
        ("SSCL", D("2.1250"), D("334.69")),
        ("VAT", D("18.0000"), D("2895.24")),
    ]
    assert note.total_amount == D("18979.93")
    note = credit_notes.submit(executive, note)
    assert Notification.objects.filter(user=director, event="approval_waiting").exists()
    note = credit_notes.approve(director, note, "OK")
    assert (note.status, note.number) == ("approved", f"{NUMBER}01")
    lines = [
        (x.account.number, x.debit, x.credit, x.customer_id)
        for x in note.journal_entry.lines.order_by("line_no")
    ]
    assert lines == [
        ("4010", D("15750.00"), 0, None),
        ("2110", D("334.69"), 0, None),
        ("2100", D("2895.24"), 0, None),
        ("1100", 0, D("18979.93"), invoice.customer_id),
    ]
    assert note.journal_entry.source_type == "credit_note"


def test_never_more_than_was_invoiced(invoice, executive, director):
    with pytest.raises(SalesError, match="at most 115,750.00 is left"):
        price(executive, invoice, "115750.01")
    with pytest.raises(SalesError, match="quantity returned"):
        credit_notes.create(
            executive, invoice, lines=line(invoice, "100"), kind="return", reason="Rusty"
        )
    with pytest.raises(SalesError, match="at most 50 pcs"):
        credit_notes.create(
            executive, invoice, lines=line(invoice, "100", "51"), kind="return", reason="Rusty"
        )
    with pytest.raises(SalesError, match="reason"):
        price(executive, invoice, "1", reason=" ")
    with pytest.raises(SalesError, match="before its invoice"):
        price(executive, invoice, "1", credit_date=invoice.invoice_date - timedelta(days=1))
    first = credit_notes.submit(executive, price(executive, invoice, "15750.00"))
    credit_notes.approve(director, first)
    with pytest.raises(SalesError, match="at most 100,000.00 is left"):
        price(executive, invoice, "100000.01")
    # Two drafts that fit alone but not together: the second is stopped at approval.
    a = credit_notes.submit(executive, price(executive, invoice, "60000"))
    b = credit_notes.submit(executive, price(executive, invoice, "60000"))
    credit_notes.approve(director, a)
    with pytest.raises(SalesError, match="another credit note has been approved"):
        credit_notes.approve(director, b)


def test_the_database_refuses_crediting_too_much(invoice, executive, director, accountant):
    a = credit_notes.submit(executive, price(executive, invoice, "60000"))
    b = credit_notes.submit(executive, price(executive, invoice, "60000"))
    credit_notes.approve(director, a)
    entry = journal.post(
        accountant,
        entry_date=TODAY,
        narration="test",
        lines=[
            Line(account=Account.objects.get(number="1010"), debit="1"),
            Line(account=Account.objects.get(number="3000"), credit="1"),
        ],
    )
    with pytest.raises(DatabaseError, match="credits more than was invoiced on line 1"):
        with transaction.atomic():
            CreditNote.objects.filter(pk=b.pk).update(
                status="approved", number="X1", journal_entry=entry
            )


# --- Approval -----------------------------------------------------------------------------------


def test_who_approves(invoice, executive, director, accountant):
    note = credit_notes.submit(executive, price(executive, invoice, "1000"))
    with pytest.raises(SalesError, match="approved by the Director"):
        credit_notes.approve(accountant, note)
    # The Admin gives the Accountant the right; it counts only once the Director confirms.
    accountant = grant(accountant, "approve_credit_notes", director, confirmed=False)
    assert not credit_notes.can_approve(accountant, note)
    AccessOverride.objects.filter(user=accountant).update(
        confirmed_by=director, confirmed_at=timezone.now()
    )
    accountant = fresh(accountant)
    assert credit_notes.can_approve(accountant, note)
    state = approvals.state_of("credit_note", note.pk)
    assert accountant in approvals.approvers(state)
    assert [s.document_id for s in approvals.waiting_for(accountant, "credit_note")] == [note.pk]
    note = credit_notes.approve(accountant, note)
    assert note.status == "approved"


def test_nobody_approves_their_own(invoice, accountant, director):
    accountant = grant(accountant, "approve_credit_notes", director)
    note = credit_notes.submit(accountant, price(accountant, invoice, "1000"))
    with pytest.raises(SalesError, match="created or submitted"):
        credit_notes.approve(accountant, note)


def test_returned_rejected_and_never_changed(invoice, executive, director):
    note = credit_notes.submit(executive, price(executive, invoice, "1000"))
    with pytest.raises(DatabaseError, match="sent for approval"):
        with transaction.atomic():
            CreditNoteLine.objects.filter(note=note).update(amount="2")
    note = credit_notes.send_back(director, note, "Wrong amount")
    note = credit_notes.save(executive, note, lines=line(invoice, "900"), reason="Corrected")
    note = credit_notes.submit(executive, note)
    note = credit_notes.reject(director, note, "No credit agreed")
    assert note.status == "rejected"
    with pytest.raises(DatabaseError, match="rejected for good"):
        with transaction.atomic():
            CreditNote.objects.filter(pk=note.pk).update(status="draft")
    with pytest.raises(SalesError, match="Only the person who made a draft"):
        credit_notes.delete(executive, note)
    approved = credit_notes.approve(
        director, credit_notes.submit(executive, price(executive, invoice, "100"))
    )
    with pytest.raises(DatabaseError, match="approved for good"):
        with transaction.atomic():
            CreditNote.objects.filter(pk=approved.pk).update(reason="changed")


def test_only_against_an_issued_invoice(executive, director, stores):
    order = base.make_order(
        executive, director, QuoteLine(description="Pin", quantity="1", unit_price="10")
    )
    base.deliver(stores, order, "1")
    draft = invoices.create(executive, order)
    with pytest.raises(SalesError, match="issued invoice"):
        price(executive, draft, "1")
    with pytest.raises(SalesError, match="Only Sales or the Accountant"):
        price(stores, draft, "1")


# --- Printing and API ------------------------------------------------------------------------


def test_the_printed_credit_note(invoice, executive, director):
    note = credit_notes.submit(executive, price(executive, invoice, "15750.00"))
    assert b"DRAFT" in credit_note_printing.render(note, compress=False)
    note = credit_notes.approve(director, note)
    text = credit_note_printing.render(note, compress=False)
    for expected in (
        "CREDIT NOTE",
        note.number,
        invoice.number,
        "134567890",
        "Price correction",
        "15,750.00",
        "334.69",
        "2,895.24",
        "18,979.93",
        f"{TODAY:%m/%d/%Y}",
    ):
        assert expected.encode() in text, expected
    assert b"DRAFT" not in text


def test_the_api(invoice, executive, director):
    client = as_user(executive)
    form = client.get(f"/api/v1/credit-notes/invoice/{invoice.pk}/").json()
    (only,) = form["lines"]
    assert (only["left_amount"], only["left_quantity"]) == ("115750.00", "50.000")
    body = {
        "invoice": invoice.pk,
        "kind": "return",
        "reason": "5 shafts returned: wrong hardness",
        "lines": [{"invoice_line": only["id"], "amount": "11575.00", "quantity": "5"}],
    }
    made = client.post("/api/v1/credit-notes/", body, format="json")
    assert made.status_code == 201, made.json()
    pk = made.json()["id"]
    assert client.post(f"/api/v1/credit-notes/{pk}/submit/").status_code == 200
    boss = as_user(director)
    assert [n["id"] for n in boss.get("/api/v1/credit-notes/?waiting=me").json()] == [pk]
    approved = boss.post(f"/api/v1/credit-notes/{pk}/approve/", {"comment": "OK"})
    assert approved.status_code == 200, approved.json()
    assert approved.json()["number"] == f"{NUMBER}01"
    assert client.get(f"/api/v1/credit-notes/{pk}/pdf/")["Content-Type"] == "application/pdf"
    detail = client.get(f"/api/v1/tax-invoices/{invoice.pk}/").json()
    assert [n["number"] for n in detail["credit_notes"]] == [f"{NUMBER}01"]
    after = client.get(f"/api/v1/credit-notes/invoice/{invoice.pk}/").json()["lines"][0]
    assert (after["left_amount"], after["left_quantity"]) == ("104175.00", "45.000")
    qc = as_user(person("qc@sml.lk", "qc_inspector"))
    assert qc.get("/api/v1/credit-notes/").status_code == 403
