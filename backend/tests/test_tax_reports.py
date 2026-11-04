# ruff: noqa: F811 - the fixtures of test_customer_receipts are imported and used by name
"""Tax reports: the VAT return and SSCL (backlog P2-20)."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting import journal, tax_reports
from apps.accounting.models import Account

from .test_access import as_user
from .test_customer_receipts import (  # noqa: F401 - fixtures used by name
    accountant,
    director,
    executive,
    order,
    setup,
    stores,
    two,
)

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()
D = Decimal


def vat_line(accountant, amount, source="BILL-7"):
    """Input VAT claimed in the books (as a supplier invoice posts it)."""
    return journal.post(
        accountant,
        entry_date=TODAY,
        narration="Supplier bill with VAT",
        lines=[
            journal.Line(account=Account.objects.get(system_role="vat_receivable"), debit=amount),
            journal.Line(account=Account.objects.get(number="1010"), credit=amount),
        ],
        source_type="supplier_invoice",
        source_id=source,
    )


def test_the_vat_return_from_the_documents_and_the_books(two, accountant):
    one, other = two
    vat_line(accountant, D("1800.00"))
    data = tax_reports.vat_return(TODAY.year, TODAY.month)
    assert data["supplies"]["standard"] == D("115750.00")  # 20 + 30 shafts at 2,315.00
    assert data["supplies"]["zero"] == D("0")
    assert [r["document"] for r in data["sales"]] == sorted([one.number, other.number])
    vat = sum(
        (t.amount for i in (one, other) for t in i.taxes.all() if t.component.code == "VAT"),
        D("0"),
    )
    assert data["output_vat"] == vat
    assert data["ledger_output_vat"] == vat  # the documents agree with the books
    assert [(r["document"], r["vat"]) for r in data["purchases"]] == [("BILL-7", D("1800.00"))]
    assert data["payable"] == vat - D("1800.00")


def test_the_sscl_report_with_its_base(two):
    data = tax_reports.sscl(TODAY.year, TODAY.month)
    assert sum((r["base"] for r in data["rows"]), D("0")) == D("115750.00")
    assert data["total"] == sum(
        (t.amount for i in two for t in i.taxes.all() if t.component.code.startswith("SSCL")),
        D("0"),
    )


def test_the_reports_through_the_api(two, accountant):
    client = as_user(accountant)
    body = client.get(f"/api/v1/tax-reports/vat/?year={TODAY.year}&month={TODAY.month}").json()
    assert body["supplies"]["standard"] == "115750.00"
    assert len(body["sales"]) == 2
    sheet = client.get(
        f"/api/v1/tax-reports/vat/?year={TODAY.year}&month={TODAY.month}&export=xlsx"
    )
    assert sheet.status_code == 200 and sheet["Content-Disposition"].endswith('.xlsx"')
    pdf = client.get(f"/api/v1/tax-reports/sscl/?year={TODAY.year}&month={TODAY.month}&export=pdf")
    assert pdf.content.startswith(b"%PDF")
