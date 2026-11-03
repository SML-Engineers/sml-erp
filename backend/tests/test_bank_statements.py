"""Bank statement import (backlog P2-15)."""

import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.accounting import services as chart
from apps.accounting.models import DetailType
from apps.banking import statements
from apps.banking.models import BankStatementLine, StatementTemplate
from apps.banking.services import BankingError
from apps.masters import banking

from .test_access import as_user, person

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


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


def combank():
    return StatementTemplate.objects.get(code="COMBANK-PDF")


ROWS = [
    ("01/10/2026", "CHQ DEP 004512 LANKA TILES", "", "20,000.00", "120,000.00 Cr"),
    ("02/10/2026", "CHQ 000100 PAID", "1,000.00", "", "119,000.00 Cr"),
    ("", "SDD POLYMER", "", "", ""),
    ("03/10/2026", "SERVICE CHARGE", "250.00", "", "118,750.00 Cr"),
]


def pdf(rows=ROWS, opening="100,000.00 Cr"):
    """A statement laid out like the Commercial Bank PDF: date, description, debit, credit,
    balance with Cr/Dr."""
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer, pagesize=A4)
    y = 800

    def row(*cols):
        nonlocal y
        for x, text in zip((40, 100, 330, 410, 490), cols, strict=False):
            if text:
                page.drawString(x, y, text)
        y -= 14

    row("Commercial Bank of Ceylon PLC")
    row("Date", "Description", "Debit", "Credit", "Balance")
    if opening:
        row("", "Balance B/F", "", "", opening)
    for r in rows:
        row(*r)
    page.showPage()
    page.save()
    return buffer.getvalue()


def bring(user, account, content, template=None, **extra):
    return statements.import_file(
        user,
        account=account,
        template=template or combank(),
        content=content,
        file_name="statement.pdf",
        **extra,
    )


def lines(statement):
    return [(x.date.day, x.money_out, x.money_in, x.balance) for x in statement.lines.all()]


def test_the_commercial_bank_pdf_is_read_line_by_line(accountant, bank):
    statement = bring(accountant, bank, pdf())
    assert lines(statement) == [
        (1, D("0"), D("20000.00"), D("120000.00")),
        (2, D("1000.00"), D("0"), D("119000.00")),
        (3, D("250.00"), D("0"), D("118750.00")),
    ]
    assert (statement.opening_balance, statement.closing_balance) == (
        D("100000.00"),
        D("118750.00"),
    )
    # The description carried over to the next line is kept.
    assert statement.lines.get(line_no=2).description == "CHQ 000100 PAID SDD POLYMER"


def test_the_same_file_once_and_overlapping_lines_skipped(accountant, bank):
    bring(accountant, bank, pdf())
    with pytest.raises(BankingError, match="imported already"):
        bring(accountant, bank, pdf())
    later = ROWS[1:] + [("05/10/2026", "INTEREST", "", "50.00", "118,800.00 Cr")]
    statement = bring(accountant, bank, pdf(later, opening="120,000.00 Cr"))
    assert (statement.skipped, lines(statement)) == (2, [(5, D("0"), D("50.00"), D("118800.00"))])


def test_a_misread_file_is_refused(accountant, bank):
    wrong = [("01/10/2026", "CHQ DEP", "", "20,000.00", "125,000.00 Cr")]
    with pytest.raises(BankingError, match="does not explain the balance going from 100,000.00 to 125,000.00"):
        bring(accountant, bank, pdf(wrong))
    assert not BankStatementLine.objects.exists()


def test_without_an_opening_balance_it_is_asked_for_or_taken_from_the_last(accountant, bank):
    one_amount = [("01/10/2026", "CHQ DEP", "20,000.00", "", "120,000.00 Cr")]
    template = statements.save_template(
        accountant,
        None,
        {"code": "test-pdf", "bank_name": "Test Bank", "file_kind": "pdf"},
    )
    with pytest.raises(BankingError, match="give the opening balance"):
        bring(accountant, bank, pdf(one_amount, opening=None), template)
    statement = bring(accountant, bank, pdf(one_amount, opening=None), template, opening="100000")
    assert lines(statement) == [(1, D("0"), D("20000.00"), D("120000.00"))]


def test_an_excel_export_with_one_signed_amount(accountant, bank):
    template = statements.save_template(
        accountant,
        None,
        {
            "code": "sampath-xlsx",
            "bank_name": "Sampath Bank",
            "file_kind": "excel",
            "date_column": "Txn Date",
            "description_column": "Narration",
            "reference_column": "Cheque No",
            "amount_column": "Amount",
            "balance_column": "Running Balance",
        },
    )
    book = Workbook()
    sheet = book.active
    sheet.append(["Sampath Bank PLC statement"])
    sheet.append(["Txn Date", "Narration", "Cheque No", "Amount", "Running Balance"])
    sheet.append(["Opening balance", None, None, None, 5000])
    sheet.append(["2026-10-01", "Transfer in", "", 1500.5, 6500.5])
    sheet.append(["2026-10-02", "Cheque paid", "000101", -500, 6000.5])
    out = io.BytesIO()
    book.save(out)
    statement = bring(accountant, bank, out.getvalue(), template)
    assert lines(statement) == [
        (1, D("0"), D("1500.50"), D("6500.50")),
        (2, D("500.00"), D("0"), D("6000.50")),
    ]
    assert statement.lines.get(line_no=2).reference == "000101"


def test_a_csv_export_with_debit_and_credit_columns(accountant, bank):
    template = statements.save_template(
        accountant, None, {"code": "hnb-csv", "bank_name": "HNB", "file_kind": "csv"}
    )
    text = (
        "Date,Description,Debit,Credit,Balance\n"
        '01/10/2026,Deposit,,"2,000.00","12,000.00"\n'
        '02/10/2026,Charges,25.00,,"11,975.00"\n'
    )
    statement = bring(accountant, bank, text.encode(), template, opening="10000.00")
    assert lines(statement) == [
        (1, D("0"), D("2000.00"), D("12000.00")),
        (2, D("25.00"), D("0"), D("11975.00")),
    ]


def test_only_the_accountant_imports(bank):
    cashier = person("cashier@sml.lk", "cashier", all_divisions=True)
    with pytest.raises(BankingError, match="Only the Accountant"):
        bring(cashier, bank, pdf())


def test_imported_lines_never_change(accountant, bank):
    statement = bring(accountant, bank, pdf())
    with pytest.raises(DatabaseError, match="never changes"), transaction.atomic():
        statement.lines.filter(line_no=1).update(money_in=D("1"))
    statements.delete(accountant, statement)  # a wrong import is deleted whole
    assert not BankStatementLine.objects.exists()


def test_preview_then_import_through_the_api(accountant, bank):
    client = as_user(accountant)
    form = {"account": bank.pk, "template": combank().pk}
    preview = client.post(
        "/api/v1/bank-statements/import/",
        form | {"preview": "1", "file": SimpleUploadedFile("s.pdf", pdf())},
        format="multipart",
    )
    assert preview.status_code == 200, preview.content
    body = preview.json()
    assert (body["opening"], len(body["lines"]), body["problems"]) == ("100000.00", 3, [])
    made = client.post(
        "/api/v1/bank-statements/import/",
        form | {"file": SimpleUploadedFile("s.pdf", pdf())},
        format="multipart",
    )
    assert made.status_code == 201, made.content
    assert made.json()["closing_balance"] == "118750.00"
