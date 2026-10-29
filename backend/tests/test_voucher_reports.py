"""Voucher lists and reports, with Excel and PDF export (backlog P1-08, spec 4.4)."""

import io
from datetime import timedelta

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounting import services as chart
from apps.accounting.models import Account, DetailType
from apps.masters import banking
from apps.payments import services as payments
from apps.vouchers import services
from apps.vouchers.services import CodingInput, LineInput

from .test_access import as_user, person
from .test_voucher_amendments import approved
from .test_vouchers import attach, draft, payee, ws

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def cashier():
    return person("cashier@sml.lk", "cashier", all_divisions=True)


def submitted(clerk, code, amount="250.00"):
    v = draft(clerk, payee(code=code), LineInput(amount=amount, invoice_no=f"I-{code}"))
    attach(clerk, v, content=b"%PDF-1.7 " + code.encode())
    return services.submit(clerk, v)


def sheet(response):
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    return load_workbook(io.BytesIO(response.content)).active


def test_the_voucher_list_exports_to_excel_and_pdf(clerk, accountant):
    submitted(clerk, "S0001", "250.00")
    submitted(clerk, "S0002", "1000.50")
    client = as_user(accountant)
    rows = list(sheet(client.get("/api/v1/vouchers/?export=xlsx")).values)
    assert rows[0][0] == "Voucher list"
    assert rows[3][0] == "Number" and rows[3][-1] == "Total (LKR)"
    assert {r[4] for r in rows[4:6]} == {"Lanka Steel (Pvt) Ltd"}
    assert rows[-1][0] == "Total" and rows[-1][-1] == 1250.5
    filtered = list(sheet(client.get("/api/v1/vouchers/?export=xlsx&q=S0002")).values)
    assert filtered[1][0] == "q: S0002"
    pdf = client.get(f"/api/v1/vouchers/?export=pdf&from={TODAY}&to={TODAY}")
    assert pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert 'filename="vouchers.pdf"' in pdf["Content-Disposition"]
    tomorrow = TODAY + timedelta(days=1)
    assert client.get(f"/api/v1/vouchers/?from={tomorrow}").json() == []


def test_the_approved_list_by_date_and_division(clerk, accountant, director, cashier):
    voucher = approved(clerk, accountant, director)
    submitted(clerk, "S0009")  # not approved: not on the list
    client = as_user(cashier)
    rows = client.get(f"/api/v1/vouchers/reports/approved/?from={TODAY}&to={TODAY}").json()
    assert [(r["number"], r["approved_by"], r["paid"]) for r in rows] == [
        (voucher.number, director.full_name, "0.00")
    ]
    tomorrow = TODAY + timedelta(days=1)
    assert client.get(f"/api/v1/vouchers/reports/approved/?from={tomorrow}").json() == []
    assert client.get("/api/v1/vouchers/reports/approved/?division=IM").json() == []
    exported = list(sheet(client.get("/api/v1/vouchers/reports/approved/?export=xlsx")).values)
    assert exported[4][0] == voucher.number and exported[4][6] == director.full_name


def test_pending_by_approver_and_age(clerk, accountant, director, cashier):
    at_l2 = submitted(clerk, "S0001")
    at_l3 = submitted(clerk, "S0002", "900.00")
    services.code_lines(
        accountant,
        at_l3,
        [CodingInput(line_no=1, account=Account.objects.get(number="6210"), division=ws())],
    )
    services.approve(accountant, at_l3)
    body = as_user(director).get("/api/v1/vouchers/reports/pending/").json()
    rows = {r["number"]: r for r in body["rows"]}
    assert rows[at_l2.number]["waiting_for"] == "L2 Accountant"
    assert rows[at_l2.number]["approvers"] == accountant.full_name
    assert rows[at_l3.number]["waiting_for"] == "L3 Director"
    assert rows[at_l3.number]["approvers"] == director.full_name
    assert {(r["days"], r["band"]) for r in body["rows"]} == {(0, "0–2 days")}
    assert [(s["waiting_for"], s["count"]) for s in body["summary"]] == [
        ("L2 Accountant", 1),
        ("L3 Director", 1),
    ]
    assert as_user(cashier).get("/api/v1/vouchers/reports/pending/").json()["rows"] == []
    pdf = as_user(director).get("/api/v1/vouchers/reports/pending/?export=pdf")
    assert pdf.content.startswith(b"%PDF")


def test_the_approval_history_of_one_voucher(clerk, accountant, director):
    voucher = approved(clerk, accountant, director)
    services.request_cancellation(accountant, voucher, "Supplier will not deliver")
    rows = as_user(director).get(f"/api/v1/vouchers/{voucher.pk}/history/").json()
    assert [(r["level"], r["action"], r["user"]) for r in rows] == [
        (1, "Submitted", clerk.full_name),
        (2, "Approved", accountant.full_name),
        (3, "Approved", director.full_name),
        (1, "Cancellation: submitted", accountant.full_name),
    ]
    assert rows[-1]["reason"] == "Supplier will not deliver"
    exported = as_user(clerk).get(f"/api/v1/vouchers/{voucher.pk}/history/?export=xlsx")
    assert list(sheet(exported).values)[0][0] == f"Approval history of voucher {voucher.number}"


def test_payments_by_period_export(clerk, accountant, director, cashier):
    ledger = chart.create_account(
        accountant,
        name="Commercial Bank current",
        account_type="bank",
        detail_type=DetailType.objects.get(name="Current account"),
        number="1030",
    )
    bank = banking.create_account(
        accountant,
        code="com-cur",
        kind="current",
        name="Commercial Bank current",
        bank_name="Commercial Bank",
        account_number="1000234567",
        ledger_account=ledger.pk,
    )
    banking.add_cheque_book(accountant, bank, first=100, last=150)
    voucher = approved(clerk, accountant, director)
    payments.record(
        cashier, voucher, account=bank, method="cheque", amount="400.00", payment_date=TODAY
    )
    client = as_user(cashier)
    rows = list(sheet(client.get(f"/api/v1/payments/?from={TODAY}&to={TODAY}&export=xlsx")).values)
    assert rows[1][0] == f"Supplier payments, {TODAY} to {TODAY}"
    assert rows[4][2] == voucher.number and rows[4][5] == "Cheque" and rows[4][-1] == 400
    assert client.get("/api/v1/payments/?method=cash").json() == []


def test_the_amendments_list_exports(clerk, accountant, director):
    original = approved(clerk, accountant, director)
    services.amend(clerk, original, "Corrected invoice")
    rows = list(sheet(as_user(accountant).get("/api/v1/vouchers/amendments/?export=xlsx")).values)
    assert rows[4][:2] == (f"{original.number}-R1", original.number)
    assert rows[4][4] == "Corrected invoice"
