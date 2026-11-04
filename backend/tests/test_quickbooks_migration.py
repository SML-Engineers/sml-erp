# ruff: noqa: F811 - the fixtures of test_journal are imported and used by name
"""Opening balances from QuickBooks' own Excel exports (backlog P2-28)."""

import io
from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from openpyxl import Workbook

from apps.accounting import quickbooks as qb
from apps.accounting.models import Account, JournalLine, OpeningBalance
from apps.accounting.quickbooks import MigrationError
from apps.masters import customers
from apps.masters.models import Currency, Supplier

from .test_access import as_user, person
from .test_journal import acc, accountant, director  # noqa: F401

pytestmark = pytest.mark.django_db
D = Decimal


def book(rows) -> bytes:
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def role(name):
    return Account.objects.get(system_role=name)


def trial_balance(cash="500000", out_by=0):
    """As QuickBooks exports it: title rows with the date, Debit/Credit in alternate columns."""
    rows = [
        ["", "SML Engineers (Pvt) Ltd"],
        ["", "Trial Balance"],
        ["", "Oct 31, 26"],
        ["", "", "Debit", "", "Credit"],
        ["", f"1010 · {acc('1010').name}", float(cash) + out_by, None, None],
        ["", role("accounts_receivable").name, 150000, None, None],
        ["", role("accounts_payable").name, None, None, 80000],
        ["", acc("4010").name, None, None, 900000],
        ["", acc("6220").name, 330000, None, None],
        ["TOTAL", "", 980000 + out_by, None, 980000],
    ]
    return book(rows)


def receivables(amounts=(100000, 50000), name="Lanka Tiles PLC"):
    rows = [
        ["", "SML Engineers (Pvt) Ltd"],
        ["", "A/R Ageing Detail"],
        ["", "Type", "", "Date", "", "Num", "", "Due Date", "", "Open Balance"],
        [name],
    ]
    rows += [
        ["", "Invoice", "", "01/10/2026", "", f"INV-{n}", "", "31/10/2026", "", a]
        for n, a in enumerate(amounts)
    ]
    rows += [
        [f"Total {name}", "", "", "", "", "", "", "", "", sum(amounts)],
        ["TOTAL", "", "", "", "", "", "", "", "", sum(amounts)],
    ]
    return book(rows)


def payables():
    return book(
        [
            ["", "A/P Ageing Detail"],
            ["", "Type", "", "Date", "", "Num", "", "Name", "", "Due Date", "", "Open Balance"],
            ["Current"],
            [
                "",
                "Bill",
                "",
                "15/10/2026",
                "",
                "B-1",
                "",
                "Shenzhen Moulds Co",
                "",
                "14/11/2026",
                "",
                80000,
            ],
            ["Total Current", "", "", "", "", "", "", "", "", "", "", 80000],
        ]
    )


@pytest.fixture
def masters():
    sales = person("sales@sml.lk", "sales_executive", all_divisions=True)
    customers.create_customer(sales, {"name": "Lanka Tiles PLC", "currency": "LKR"})
    Supplier.objects.create(
        code="S0050",
        name="Shenzhen Moulds Co",
        currency=Currency.objects.get(code="LKR"),
        payment_terms_days=30,
    )


def files(**changes):
    return {
        "trial_balance": trial_balance(),
        "receivables": receivables(),
        "payables": payables(),
    } | changes


def test_quickbooks_files_become_one_opening_entry_approved_by_the_director(
    accountant, director, masters
):
    found = qb.check(**files())
    report = found["report"]
    assert report["errors"] == [], report
    assert (report["as_at"], report["debits"], report["receivables"], report["payables"]) == (
        "2026-10-31",
        "980000.00",
        "150000.00",
        "80000.00",
    )
    doc = qb.make(accountant, **files())
    lines = {
        (x.account.system_role or x.account.number, x.debit, x.credit)
        for x in doc.lines.select_related("account")
    }
    assert lines == {
        ("1010", D("500000.00"), 0),
        ("accounts_receivable", D("150000.00"), 0),
        ("accounts_payable", 0, D("80000.00")),
        ("retained_earnings", 0, D("570000.00")),  # 900,000 sales less 330,000 costs
    }
    qb.submit(accountant, doc)
    with pytest.raises(MigrationError):
        qb.approve(accountant, doc)  # nobody approves their own
    doc = qb.approve(director, doc)
    assert doc.status == "posted" and doc.journal_entry.entry_date == date(2026, 10, 31)
    debtor = JournalLine.objects.get(entry=doc.journal_entry, account=role("accounts_receivable"))
    assert debtor.customer.name == "Lanka Tiles PLC"
    with transaction.atomic(), pytest.raises(DatabaseError, match="never change"):
        OpeningBalance.objects.filter(pk=doc.pk).update(as_at=date(2026, 1, 1))
    with pytest.raises(MigrationError, match="posted already"):
        qb.make(accountant, **files())


def test_the_check_lists_everything_wrong(accountant, masters):
    report = qb.check(**files(trial_balance=trial_balance(out_by=6750)))["report"]
    assert any("out by 6,750.00" in e for e in report["errors"])
    report = qb.check(**files(receivables=receivables(amounts=(100000,))))["report"]
    assert any("open invoices add up to 100,000.00" in e for e in report["errors"])
    report = qb.check(**files(receivables=receivables(name="Unknown Traders")))["report"]
    assert any("Unknown Traders" in e for e in report["errors"])
    report = qb.check(trial_balance=trial_balance())["report"]
    assert any("upload the A/R aging" in e for e in report["errors"])
    with pytest.raises(MigrationError, match="Correct what the check found"):
        qb.make(accountant, trial_balance=trial_balance())
    with pytest.raises(MigrationError, match="not an Excel workbook"):
        qb.check(trial_balance=b"not a file")


def test_an_unknown_account_is_named(masters):
    content = book(
        [
            ["", "Oct 31, 26"],
            ["", "", "Debit", "", "Credit"],
            ["", "Fuel for the forklift", 10, None, None],
            ["", f"1010 · {acc('1010').name}", None, None, 10],
        ]
    )
    report = qb.check(trial_balance=content)["report"]
    assert any("Fuel for the forklift" in e for e in report["errors"])


def test_the_item_list_is_valued():
    content = book(
        [
            ["", "Item", "", "Description", "", "Type", "", "Cost", "", "Quantity On Hand"],
            ["", "PP-H001", "", "PP resin", "", "Stock Part", "", 450, "", 1000],
            ["", "Labour", "", "", "", "Service", "", 0, "", 0],
            ["", "Gloves", "", "", "", "Non-stock Part", "", 50, "", 10],
        ]
    )
    assert qb.read_items(content) == {"value": D("450000.00"), "items": 1}


def test_the_screens_api(accountant, masters):
    api = as_user(accountant)
    upload = {k: SimpleUploadedFile(f"{k}.xlsx", v) for k, v in files().items()}
    checked = api.post("/api/v1/migration/", upload, format="multipart")
    assert checked.status_code == 200, checked.json()
    assert checked.json()["report"]["errors"] == [] and checked.json()["document"] is None
    upload = {k: SimpleUploadedFile(f"{k}.xlsx", v) for k, v in files().items()} | {"make": "yes"}
    made = api.post("/api/v1/migration/", upload, format="multipart")
    assert made.status_code == 200 and made.json()["document"]["status"] == "draft"
    listed = api.get("/api/v1/migration/").json()
    assert listed["documents"][0]["total_debit"] == "650000.00"
    clerk = as_user(person("clerk@sml.lk", "clerk", all_divisions=True))
    assert clerk.get("/api/v1/migration/").status_code == 403
