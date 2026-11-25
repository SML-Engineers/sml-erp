# ruff: noqa: F811 (pytest fixtures imported from test_supplier_returns)
"""The supplier's credit note matched to our debit note (owner, 22 Nov 2026: our debit note
is raised when invoiced goods leave; the supplier's credit note is matched to it later)."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting.models import JournalEntry
from apps.core.models import AuditEvent
from apps.purchasing import credit_notes, payables, returns
from apps.purchasing.credit_notes import CreditNoteError
from apps.purchasing.models import DebitNote, SupplierCreditNote

from .test_access import as_user, person
from .test_supplier_returns import (  # noqa: F401
    PDF,
    buyer,
    clerk,
    director,
    give_back,
    inspect,
    invoice,
    line,
    memory_storage,
    qc,
    stores,
)

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def note(stores, qc, clerk, director, line):
    """Our debit note for 10 inserts (LKR 1,000.00) returned after being invoiced."""
    inspect(qc, line)
    invoice(clerk, line, "100")
    returns.approve(director, returns.confirm(stores, give_back(stores, line, "accepted", "10")))
    return DebitNote.objects.get()


def scan(name="cn.pdf"):
    return SimpleUploadedFile(name, PDF, content_type="application/pdf")


def url(note, end=""):
    return f"/api/v1/supplier-invoices/{note.invoice_id}/debit-notes/{note.pk}/credit-note/{end}"


def test_the_clerk_records_the_suppliers_credit_note_and_nothing_is_posted(clerk, note):
    entries = JournalEntry.objects.count()
    response = as_user(clerk).post(
        url(note), {"number": "SCN-0055", "date": TODAY.isoformat(), "file": scan()}
    )
    assert response.status_code == 201, response.json()
    shown = response.json()["debit_notes"][0]["credit_note"]
    assert (shown["number"], shown["date"], shown["file_name"]) == (
        "SCN-0055",
        TODAY.isoformat(),
        "cn.pdf",
    )
    assert JournalEntry.objects.count() == entries  # our debit note already posted
    assert AuditEvent.objects.filter(event="supplier_credit_note_recorded").exists()
    opened = as_user(clerk).get(url(note))
    assert opened.status_code == 200 and b"".join(opened.streaming_content) == PDF


@pytest.mark.parametrize(
    "values, message",
    [
        ({"number": " ", "date": TODAY}, "Give the supplier's credit note number."),
        ({"number": "C1", "date": "31/12/2026"}, "Give the date of the supplier's credit note"),
        ({"number": "C1", "date": TODAY + timedelta(days=1)}, "cannot be dated in the future"),
        ({"number": "C1", "date": TODAY - timedelta(days=1)}, "dated before the invoice"),
        ({"number": "C1", "date": TODAY, "file": None}, "Attach the scan"),
        (
            {"number": "C1", "date": TODAY, "file": SimpleUploadedFile("x.txt", b"hello")},
            "Only JPG, PNG and PDF",
        ),
    ],
)
def test_wrong_details_are_refused_in_plain_words(clerk, note, values, message):
    uploaded = values.pop("file", scan())
    with pytest.raises(CreditNoteError, match=message):
        credit_notes.record(
            clerk, note, number=values["number"], credit_date=values["date"], uploaded=uploaded
        )
    assert not SupplierCreditNote.objects.exists()


def test_a_debit_note_has_one_credit_note_and_it_is_never_changed(clerk, note):
    credit = credit_notes.record(clerk, note, number="C1", credit_date=TODAY, uploaded=scan())
    with pytest.raises(CreditNoteError, match="already has the supplier's credit note C1"):
        credit_notes.record(clerk, note, number="C2", credit_date=TODAY, uploaded=scan())
    with pytest.raises(DatabaseError, match="cannot be changed"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE purchasing_suppliercreditnote SET credit_note_no = 'C9' WHERE id = %s",
                [credit.pk],
            )


def test_the_database_refuses_a_blank_number_or_a_future_date(clerk, note):
    for number, day, message in (
        ("  ", TODAY, "number is required"),
        ("C1", TODAY + timedelta(days=2), "cannot be dated in the future"),
    ):
        with pytest.raises(DatabaseError, match=message), transaction.atomic():
            SupplierCreditNote.objects.create(
                debit_note=note,
                credit_note_no=number,
                credit_note_date=day,
                file="x.pdf",
                file_name="x.pdf",
                content_type="application/pdf",
                size=1,
                sha256="0",
                recorded_by=clerk,
            )


def test_only_the_accountant_removes_a_mistake_with_a_reason(clerk, accountant, note):
    credit_notes.record(clerk, note, number="C1", credit_date=TODAY, uploaded=scan())
    assert as_user(clerk).post(url(note, "remove/"), {"reason": "x"}).status_code == 400
    refused = as_user(accountant).post(url(note, "remove/"), {"reason": " "})
    assert refused.json()["detail"] == "Give the reason for removing the credit note."
    done = as_user(accountant).post(url(note, "remove/"), {"reason": "wrong supplier number"})
    assert done.status_code == 200 and done.json()["debit_notes"][0]["credit_note"] is None
    removed = AuditEvent.objects.get(event="supplier_credit_note_removed")
    assert removed.reason == "wrong supplier number"


def test_people_who_cannot_record_are_refused(note, stores):
    with pytest.raises(CreditNoteError, match="Only the Accounts Clerk or the Accountant"):
        credit_notes.record(stores, note, number="C1", credit_date=TODAY, uploaded=scan())


def test_the_list_shows_debit_notes_still_waiting_for_the_suppliers_credit_note(
    clerk, accountant, note
):
    rows = as_user(accountant).get("/api/v1/purchasing-reports/debit-notes/?waiting=1").json()
    assert [(r["number"], r["total_lkr"], r["days_waiting"]) for r in rows] == [
        (note.number, "1000.00", 0)
    ]
    credit_notes.record(clerk, note, number="SCN-0055", credit_date=TODAY, uploaded=scan())
    assert as_user(accountant).get("/api/v1/purchasing-reports/debit-notes/?waiting=1").json() == []
    row = as_user(accountant).get("/api/v1/purchasing-reports/debit-notes/").json()[0]
    assert (row["credit_note"], row["credit_note_date"], row["days_waiting"]) == (
        "SCN-0055",
        TODAY.isoformat(),
        None,
    )
    excel = as_user(accountant).get("/api/v1/purchasing-reports/debit-notes/?export=xlsx")
    assert excel.status_code == 200


def test_the_supplier_statement_check_knows_their_credit_note_number(clerk, note):
    credit_notes.record(clerk, note, number="SCN-0055", credit_date=TODAY, uploaded=scan())
    supplier = note.invoice.supplier
    _, credits = payables.our_records(supplier, supplier.currency, TODAY, TODAY)
    found = next(c for c in credits if c["document"] == note.number)
    assert payables._same(payables._key("scn 0055"), found["keys"])
    assert found["reference"] == f"{note.number} / SCN-0055"
