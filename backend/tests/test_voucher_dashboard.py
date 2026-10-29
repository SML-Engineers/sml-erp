"""The vouchers dashboard (backlog P1-08b): figures for the user's role and divisions that
match the lists they open."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting import services as chart
from apps.accounting.models import Account, DetailType
from apps.core.models import Division
from apps.masters import banking
from apps.payments import services as payments
from apps.vouchers import services
from apps.vouchers.models import VoucherType
from apps.vouchers.services import CodingInput, LineInput

from .test_access import as_user, person
from .test_voucher_amendments import approved
from .test_vouchers import attach, payee

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


def voucher_in(clerk, division, code, amount, submit=True):
    v = services.save(
        clerk,
        None,
        voucher_type=VoucherType.objects.get(code="CHQ"),
        division=Division.objects.get(code=division),
        payee=payee(code=code),
        lines=[LineInput(amount=amount, invoice_no=f"I-{code}")],
    )
    if submit:
        attach(clerk, v, content=b"%PDF-1.7 " + code.encode())
        v = services.submit(clerk, v)
    return v


@pytest.fixture
def scene(clerk, accountant, director, cashier):
    """WS: one voucher approved (1,000.00, 400.00 paid), one at L3 (900.00), one at L2
    (250.00). IM: one at L2 (300.00). The Clerk also has a draft."""
    paid_part = approved(clerk, accountant, director)
    at_l3 = voucher_in(clerk, "WS", "S0010", "900.00")
    services.code_lines(
        accountant,
        at_l3,
        [
            CodingInput(
                line_no=1,
                account=Account.objects.get(number="6210"),
                division=Division.objects.get(code="WS"),
            )
        ],
    )
    services.approve(accountant, at_l3)
    voucher_in(clerk, "WS", "S0011", "250.00")
    voucher_in(clerk, "IM", "S0012", "300.00")
    voucher_in(clerk, "WS", "S0013", "75.00", submit=False)
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
    payments.record(
        cashier, paid_part, account=bank, method="cheque", amount="400.00", payment_date=TODAY
    )
    return paid_part


def test_the_accountant_sees_the_whole_picture(accountant, scene):
    body = as_user(accountant).get("/api/v1/vouchers/dashboard/").json()
    assert body["waiting_for_me"] == {"count": 2, "total": "550.00"}  # WS 250 + IM 300 at L2
    assert [(r["waiting_for"], r["count"], r["total"]) for r in body["by_level"]] == [
        ("L2 Accountant", 2, "550.00"),
        ("L3 Director", 1, "900.00"),
    ]
    assert body["by_level"][0]["bands"]["0–2 days"] == 2
    assert body["unpaid"] == {"count": 1, "total": "1000.00", "remaining": "600.00"}
    assert body["paid_this_month"]["total"] == "400.00"
    assert body["paid_this_month"]["from"] == TODAY.replace(day=1).isoformat()
    ws = next(d for d in body["by_division"] if d["code"] == "WS")
    im = next(d for d in body["by_division"] if d["code"] == "IM")
    assert (ws["pending"], ws["pending_total"], ws["unpaid"]["remaining"]) == (
        2,
        "1150.00",
        "600.00",
    )
    assert (im["pending"], im["pending_total"], im["paid_this_month"]) == (1, "300.00", "0.00")
    assert [r["number"] for r in body["oldest"]][:1] == [body["oldest"][0]["number"]]


def test_the_figures_match_the_lists_they_open(accountant, cashier, scene):
    client = as_user(accountant)
    body = client.get("/api/v1/vouchers/dashboard/?division=WS").json()
    assert body["division"] == "WS"
    pending = client.get("/api/v1/vouchers/reports/pending/?division=WS").json()["rows"]
    assert len(pending) == body["pending_count"] == 2
    level_two = client.get("/api/v1/vouchers/reports/pending/?division=WS&level=2").json()
    assert len(level_two["rows"]) == body["by_level"][0]["count"] == 1
    to_pay = as_user(cashier).get("/api/v1/payments/to-pay/").json()
    left = sum(Decimal(r["remaining"]) for r in to_pay if r["division"] == "WS")
    assert f"{left:.2f}" == body["unpaid"]["remaining"]
    month = body["paid_this_month"]
    made = as_user(cashier).get(f"/api/v1/payments/?from={month['from']}&to={month['to']}").json()
    assert f"{sum(Decimal(p['amount']) for p in made):.2f}" == month["total"]


def test_each_person_sees_their_own_part(clerk, director, cashier, scene):
    clerk_view = as_user(clerk).get("/api/v1/vouchers/dashboard/").json()
    assert clerk_view["my_vouchers"]["draft"] == {"count": 1, "total": "75.00"}
    assert clerk_view["waiting_for_me"] == {"count": 0, "total": "0.00"}
    assert clerk_view["paid_this_month"] is None  # the Clerk does not see payments
    assert as_user(director).get("/api/v1/vouchers/dashboard/").json()["waiting_for_me"] == {
        "count": 1,
        "total": "900.00",
    }
    cashier_view = as_user(cashier).get("/api/v1/vouchers/dashboard/").json()
    assert cashier_view["pending_count"] == 0  # the Cashier sees approved vouchers only
    assert cashier_view["unpaid"]["remaining"] == "600.00"


def test_a_user_only_sees_their_divisions(scene):
    im_only = person("im.cashier@sml.lk", "cashier", divisions=("IM",))
    body = as_user(im_only).get("/api/v1/vouchers/dashboard/").json()
    assert [d["code"] for d in body["by_division"]] == ["IM"]
    assert body["unpaid"] == {"count": 0, "total": "0.00", "remaining": "0.00"}
    assert body["paid_this_month"]["total"] == "0.00"  # the WS payment is not theirs to see
    ws_view = as_user(im_only).get("/api/v1/vouchers/dashboard/?division=WS").json()
    assert ws_view["by_division"] == [] and ws_view["unpaid"]["count"] == 0
