"""Manual journals with approval (backlog P2-01, spec 6 and 4.6)."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import journal, manual
from apps.accounting.journal import Line
from apps.accounting.manual import LineInput
from apps.accounting.models import (
    Account,
    AccountingPeriod,
    JournalEntry,
    ManualJournal,
    ManualJournalLine,
)
from apps.accounting.services import AccountingError
from apps.core.models import ApprovalLog, Division, Notification
from apps.masters.models import Currency, Supplier

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
PDF = b"%PDF-1.4\n" + b"0" * 64


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", all_divisions=True)


@pytest.fixture
def supplier():
    return Supplier.objects.create(
        code="S0001", name="Lanka Steel", currency=Currency.objects.get(code="LKR")
    )


def acc(number):
    return Account.objects.get(number=number)


def div(code):
    return Division.objects.get(code=code)


def accrual(amount="25000.00"):
    """Accrue a repair bill: Dr Building repairs (WS), Cr Accrued expenses."""
    return [
        LineInput(acc("6220"), debit=amount, division=div("WS"), description="October repairs"),
        LineInput(acc("2170"), credit=amount),
    ]


def make(accountant, lines=None, **values):
    values.setdefault("entry_date", TODAY)
    values.setdefault("narration", "Accrue October repairs")
    return manual.create(accountant, lines=lines or accrual(), **values)


def check_deferred():
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


# --- Entering ---------------------------------------------------------------------------------


def test_the_accountant_enters_a_numbered_draft(accountant):
    mj = make(accountant)
    assert mj.number == f"MJ{TODAY:%y%m%d}01"
    assert mj.status == "draft"
    assert [(x.line_no, x.account.number, str(x.debit), str(x.credit)) for x in mj.lines.all()] == [
        (1, "6220", "25000.00", "0.00"),
        (2, "2170", "0.00", "25000.00"),
    ]
    assert not JournalEntry.objects.exists()  # nothing reaches the ledger before approval


def test_only_accounting_enter_can_make_a_journal(clerk, director):
    for user in (clerk, director):
        with pytest.raises(AccountingError, match="Only the Accountant"):
            make(user)


def test_line_rules(accountant, supplier):
    cases = [
        ([], "Add the journal's lines"),
        ([LineInput(None, debit="1")], "choose the account"),
        ([LineInput(acc("2170"), debit="1", credit="1")], "either a debit or a credit"),
        ([LineInput(acc("2170"), debit="-5")], "cannot be negative"),
        ([LineInput(acc("2170"), debit="1.005")], "to the cent"),
        ([LineInput(acc("6220"), debit="10")], "choose the division"),
        ([LineInput(acc("1100"), debit="10")], "customer balances change only"),
        ([LineInput(acc("2000"), debit="10")], "needs the supplier"),
        ([LineInput(acc("2170"), debit="10", supplier=supplier)], "only on an accounts payable"),
    ]
    for lines, why in cases:
        with pytest.raises(AccountingError, match=why):
            make(accountant, lines=lines)
    with pytest.raises(AccountingError, match="narration is required"):
        make(accountant, narration="  ")


def test_a_journal_cannot_pay_a_supplier_from_the_bank(accountant, supplier):
    lines = [
        LineInput(acc("2000"), debit="5000", supplier=supplier),
        LineInput(acc("1010"), credit="5000"),
    ]
    with pytest.raises(AccountingError, match="paid only through an approved voucher"):
        make(accountant, lines=lines)
    # A payables adjustment that is not a payment is allowed, e.g. a small balance written off.
    lines = [
        LineInput(acc("2000"), debit="12.50", supplier=supplier),
        LineInput(acc("4010"), credit="12.50", division=div("WS")),
    ]
    assert make(accountant, lines=lines).lines.count() == 2


def test_the_database_refuses_paying_a_supplier_outside_a_payment(accountant, supplier):
    with pytest.raises(DatabaseError, match="paid only through an approved voucher"):
        with transaction.atomic():
            journal.post(
                accountant,
                entry_date=TODAY,
                narration="Paid by journal",
                lines=[
                    Line(account=acc("2000"), debit="5000", supplier=supplier),
                    Line(account=acc("1010"), credit="5000"),
                ],
                source_type="manual_journal",
            )
            check_deferred()


def test_a_closed_month_is_refused(accountant, director):
    last_month = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)
    journal.set_closed(director, last_month, True, "Month-end done")
    with pytest.raises(AccountingError, match="closed"):
        make(accountant, entry_date=last_month)


def test_a_draft_is_changed_and_deleted_only_by_its_author(accountant):
    mj = make(accountant)
    other = person("accountant2@sml.lk", "accountant", all_divisions=True)
    with pytest.raises(AccountingError, match="Only the person who made"):
        manual.save(other, mj, lines=accrual("1.00"))
    mj = manual.save(accountant, mj, lines=accrual("30000.00"), narration="Accrue repairs")
    assert manual.totals(mj) == (30000, 30000)
    with pytest.raises(AccountingError, match="Only the person who made"):
        manual.delete(other, mj)
    manual.delete(accountant, mj)
    assert not ManualJournal.objects.exists()


# --- Approval -----------------------------------------------------------------------------------


def test_an_unbalanced_journal_cannot_be_sent(accountant):
    lines = [
        LineInput(acc("6220"), debit="100", division=div("WS")),
        LineInput(acc("2170"), "0", "90"),
    ]
    mj = make(accountant, lines=lines)
    with pytest.raises(AccountingError, match="does not balance"):
        manual.submit(accountant, mj)


def test_the_director_approves_and_the_journal_is_posted(accountant, director):
    mj = manual.submit(accountant, make(accountant), "Repairs bill not yet received")
    assert mj.status == "awaiting_approval"
    assert Notification.objects.filter(user=director).exists()
    with pytest.raises(AccountingError, match="approved by the Director"):
        manual.approve(accountant, mj)
    with pytest.raises(AccountingError, match="Only the person who made a draft"):
        manual.save(accountant, mj, lines=accrual("1.00"))
    mj = manual.approve(director, mj, "OK")
    mj.refresh_from_db()
    assert mj.status == "posted"
    entry = mj.journal_entry
    assert (entry.source_type, entry.source_id, entry.posted_by) == (
        "manual_journal",
        mj.number,
        director,
    )
    assert entry.narration == f"{mj.number}: Accrue October repairs"
    assert [
        (x.account.number, str(x.debit), str(x.credit), x.division_id) for x in entry.lines.all()
    ] == [
        ("6220", "25000.00", "0.00", div("WS").pk),
        ("2170", "0.00", "25000.00", None),
    ]
    # Corrected only by reversing the entry.
    reversal = journal.reverse(accountant, entry, reason="Bill came in at a different amount")
    assert reversal.reversal_of == entry


def test_returned_journals_are_corrected_and_sent_again(accountant, director):
    mj = manual.submit(accountant, make(accountant))
    with pytest.raises(AccountingError, match="reason"):
        manual.send_back(director, mj, "")
    mj = manual.send_back(director, mj, "Use the repairs account for machines")
    assert mj.status == "draft"
    mj = manual.save(accountant, mj, lines=accrual("26000.00"))
    mj = manual.submit(accountant, mj)
    mj = manual.approve(director, mj)
    assert mj.status == "posted"
    actions = list(
        ApprovalLog.objects.filter(document_type="manual_journal", document_id=mj.pk)
        .order_by("pk")
        .values_list("action", flat=True)
    )
    assert actions == ["submit", "return", "submit", "approve"]


def test_rejected_journals_stay_rejected(accountant, director):
    mj = manual.reject(director, manual.submit(accountant, make(accountant)), "Not needed")
    assert mj.status == "rejected"
    assert not JournalEntry.objects.exists()
    with pytest.raises(AccountingError, match="not waiting"):
        manual.approve(director, mj)


def test_approval_into_a_month_closed_meanwhile_posts_nothing(accountant, director):
    mj = manual.submit(accountant, make(accountant))
    AccountingPeriod.objects.update_or_create(
        month=TODAY.replace(day=1), defaults={"is_closed": True}
    )
    with pytest.raises(AccountingError, match="closed"):
        manual.approve(director, mj)
    mj.refresh_from_db()
    assert mj.status == "awaiting_approval"
    assert not JournalEntry.objects.exists()


# --- Database guards --------------------------------------------------------------------------


def test_the_database_refuses_changing_a_journal_once_sent(accountant, director):
    mj = manual.submit(accountant, make(accountant))
    with pytest.raises(DatabaseError, match="sent for approval"):
        with transaction.atomic():
            ManualJournal.objects.filter(pk=mj.pk).update(narration="Changed")
    with pytest.raises(DatabaseError, match="sent for approval"):
        with transaction.atomic():
            ManualJournalLine.objects.filter(journal=mj).update(debit="1.00")
    with pytest.raises(DatabaseError, match="cannot be deleted"):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM accounting_manualjournal WHERE id = %s", [mj.pk])
    manual.approve(director, mj)
    with pytest.raises(DatabaseError, match="for good"):
        with transaction.atomic():
            ManualJournal.objects.filter(pk=mj.pk).update(status="draft")


# --- Files and the API ----------------------------------------------------------------------------


def test_supporting_files_only_on_drafts(accountant, director):
    mj = make(accountant)
    manual.add_attachment(accountant, mj, SimpleUploadedFile("bill.pdf", PDF))
    with pytest.raises(AccountingError, match="Only JPG, PNG and PDF"):
        manual.add_attachment(accountant, mj, SimpleUploadedFile("bill.txt", b"hello"))
    mj = manual.submit(accountant, mj)
    with pytest.raises(AccountingError, match="while the journal is a draft"):
        manual.add_attachment(accountant, mj, SimpleUploadedFile("more.pdf", PDF))
    assert mj.attachments.count() == 1


def test_the_api_from_entry_to_posting(accountant, director, clerk):
    body = {
        "entry_date": TODAY.isoformat(),
        "narration": "Accrue October repairs",
        "lines": [
            {"account": acc("6220").pk, "debit": "25000.00", "division": "WS"},
            {"account": acc("2170").pk, "credit": "25000.00"},
        ],
    }
    assert as_user(clerk).get("/api/v1/manual-journals/").status_code == 403
    client = as_user(accountant)
    made = client.post("/api/v1/manual-journals/", body, format="json")
    assert made.status_code == 201, made.content
    pk = made.json()["id"]
    assert made.json()["can_edit"] is True
    upload = client.post(
        f"/api/v1/manual-journals/{pk}/attachments/",
        {"file": SimpleUploadedFile("bill.pdf", PDF)},
        format="multipart",
    )
    assert upload.status_code == 201
    assert client.post(f"/api/v1/manual-journals/{pk}/submit/").status_code == 200
    boss = as_user(director)
    assert boss.post("/api/v1/manual-journals/", body, format="json").status_code == 403
    waiting = boss.get("/api/v1/manual-journals/?waiting=me").json()
    assert [(r["id"], r["total_debit"]) for r in waiting] == [(pk, "25000.00")]
    detail = boss.get(f"/api/v1/manual-journals/{pk}/").json()
    assert detail["can_approve"] is True and detail["can_edit"] is False
    assert client.post(f"/api/v1/manual-journals/{pk}/approve/").status_code == 400
    approved = boss.post(f"/api/v1/manual-journals/{pk}/approve/", {"comment": "OK"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "posted"
    assert approved.json()["journal_entry"]["number"].startswith("JV")
    export = client.get("/api/v1/manual-journals/?export=xlsx")
    assert export.status_code == 200
    assert export["Content-Disposition"].endswith('manual-journals.xlsx"')
