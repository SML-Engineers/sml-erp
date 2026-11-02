"""Trial balance, balance sheet and general ledger (backlog P2-03, spec 6)."""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounting import journal, manual, reports, services
from apps.accounting.journal import Line
from apps.accounting.manual import LineInput
from apps.accounting.models import Account
from apps.accounting.services import AccountingError
from apps.core.models import Division

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
MONTH_START = TODAY.replace(day=1)
LAST_MONTH_END = MONTH_START - timedelta(days=1)
LAST_MONTH = LAST_MONTH_END.replace(day=1)
D = Decimal


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def acc(number):
    return Account.objects.get(number=number)


def div(code):
    return Division.objects.get(code=code)


def post(user, on, *lines, narration="Test entry"):
    return journal.post(user, entry_date=on, narration=narration, lines=list(lines))


@pytest.fixture
def books(accountant):
    """Capital last month; this month a WS sale, an IM repair and IM stock on accrual."""
    post(
        accountant,
        LAST_MONTH,
        Line(account=acc("1010"), debit="1000000.00"),
        Line(account=acc("3000"), credit="1000000.00"),
        narration="Share capital paid in",
    )
    post(
        accountant,
        TODAY,
        Line(account=acc("1010"), debit="115750.00"),
        Line(account=acc("4010"), credit="115750.00", division=div("WS")),
        narration="Cash sale",
    )
    post(
        accountant,
        TODAY,
        Line(account=acc("6210"), debit="3000.00", division=div("IM")),
        Line(account=acc("1010"), credit="3000.00"),
        narration="Machine repair",
    )
    post(
        accountant,
        TODAY,
        Line(account=acc("1210"), debit="50000.00", division=div("IM")),
        Line(account=acc("2170"), credit="50000.00", division=div("IM")),
        narration="Resin received, bill to come",
    )


def tb(rows):
    return {r.account.number: (r.debit, r.credit) for r in rows}


# --- Trial balance ---------------------------------------------------------------------------


def test_the_trial_balance_balances_and_compares(books):
    rows, other = reports.trial_balance(TODAY, compare="month")
    assert other == LAST_MONTH_END
    assert tb(rows) == {
        "1010": (D("1112750.00"), 0),
        "1210": (D("50000.00"), 0),
        "2170": (0, D("50000.00")),
        "3000": (0, D("1000000.00")),
        "4010": (0, D("115750.00")),
        "6210": (D("3000.00"), 0),
    }
    assert sum(r.debit for r in rows) == sum(r.credit for r in rows) == D("1165750.00")
    then = {r.account.number: (r.compare_debit, r.compare_credit) for r in rows}
    assert then["1010"] == (D("1000000.00"), 0) and then["4010"] == (0, 0)


def test_sub_accounts_roll_up_into_their_parent(books):
    rows, _ = reports.trial_balance(TODAY, roll_up_subaccounts=True)
    assert set(tb(rows)) == {"1010", "1200", "2170", "3000", "4000", "6200"}
    names = {r.account.number: r.account.name for r in reports.trial_balance(TODAY)[0]}
    assert names["4010"] == "Sales:Machined parts and machining services"


def test_a_division_s_trial_balance_has_only_its_lines(books):
    rows, _ = reports.trial_balance(TODAY, div("IM"))
    assert tb(rows) == {
        "1210": (D("50000.00"), 0),
        "2170": (0, D("50000.00")),
        "6210": (D("3000.00"), 0),
    }


def test_the_comparison_dates():
    from datetime import date

    assert reports.compare_date(date(2028, 2, 29), "year") == date(2027, 2, 28)
    assert reports.compare_date(date(2026, 3, 15), "month") == date(2026, 2, 28)
    assert reports.compare_date(date(2026, 3, 15), "") is None
    with pytest.raises(AccountingError):
        reports.compare_date(date(2026, 3, 15), "week")


# --- Balance sheet ---------------------------------------------------------------------------


def sheet(sections):
    return {s.key: ({r.label: r.amount for r in s.rows}, s.total()[0]) for s in sections}


def test_the_balance_sheet_balances_with_the_profit_in_equity(books):
    sections, _ = reports.balance_sheet(TODAY, compare="month")
    got = sheet(sections)
    assert got["assets"] == (
        {"1010 Cash on hand": D("1112750.00"), "1210 Inventory:Raw materials": D("50000.00")},
        D("1162750.00"),
    )
    assert got["liabilities"][1] == D("50000.00")
    assert got["equity"][0] == {
        "3000 Share capital": D("1000000.00"),
        reports.PROFIT_LABEL: D("112750.00"),
    }
    assert got["assets"][1] == got["liabilities"][1] + got["equity"][1]
    last = {r.label: r.compare for r in sections[0].rows}
    assert last["1010 Cash on hand"] == D("1000000.00")


def test_a_division_s_balance_sheet_shows_what_the_company_funds(books):
    got = sheet(reports.balance_sheet(TODAY, div("IM"))[0])
    assert got["assets"][1] == D("50000.00")
    assert got["equity"][0] == {
        reports.PROFIT_LABEL: D("-3000.00"),
        reports.COMPANY_LABEL: D("3000.00"),
    }
    assert got["assets"][1] == got["liabilities"][1] + got["equity"][1]


# --- General ledger --------------------------------------------------------------------------


def test_the_ledger_brings_forward_and_runs_the_balance(books):
    (cash,) = reports.general_ledger(MONTH_START, TODAY, account=acc("1010"))
    assert cash.opening == D("1000000.00")
    assert [(x.narration, x.balance) for x in cash.lines] == [
        ("Cash sale", D("1115750.00")),
        ("Machine repair", D("1112750.00")),
    ]
    assert cash.closing == D("1112750.00")
    everything = reports.general_ledger(MONTH_START, TODAY)
    assert {x.account.number for x in everything} == {
        "1010",
        "1210",
        "2170",
        "3000",
        "4010",
        "6210",
    }
    with pytest.raises(AccountingError, match="before the start"):
        reports.general_ledger(TODAY, TODAY - timedelta(days=1))


def test_merged_and_sub_accounts_in_the_ledger(accountant):
    for number, amount in (("6230", "300.00"), ("6220", "200.00"), ("6210", "50.00")):
        post(
            accountant,
            TODAY,
            Line(account=acc(number), debit=amount, division=div("WS")),
            Line(account=acc("1010"), credit=amount),
        )
    services.merge_accounts(accountant, acc("6230"), acc("6220"), "one repairs account")
    (repairs,) = reports.general_ledger(TODAY, TODAY, account=acc("6220"))
    assert repairs.closing == D("500.00")
    (parent,) = reports.general_ledger(TODAY, TODAY, account=acc("6200"), with_subaccounts=True)
    assert parent.closing == D("550.00")
    company = {x.account.number: x.closing for x in reports.general_ledger(TODAY, TODAY)}
    assert "6230" not in company and company["6220"] == D("500.00")


# --- API -------------------------------------------------------------------------------------


def test_the_api(books, accountant, director):
    client = as_user(director)
    body = client.get(f"/api/v1/reports/trial-balance/?as_at={TODAY}&compare=year").json()
    assert body["total_debit"] == body["total_credit"] == "1165750.00"
    assert body["rows"][0]["account"]["number"] == "1010"
    sheet_ = client.get("/api/v1/reports/balance-sheet/?division=IM").json()
    assert sheet_["division"] == "IM"
    assert [s["total"] for s in sheet_["sections"]] == ["50000.00", "50000.00", "0.00"]
    pk = acc("1010").pk
    ledger = client.get(f"/api/v1/reports/general-ledger/?account={pk}&from={MONTH_START}").json()
    (cash,) = ledger["accounts"]
    assert (cash["opening"], cash["closing"]) == ("1000000.00", "1112750.00")
    assert cash["lines"][0]["entry"]["number"].startswith("JV")
    assert client.get("/api/v1/reports/trial-balance/?as_at=yesterday").status_code == 400
    assert client.get("/api/v1/reports/trial-balance/?compare=week").status_code == 400
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get("/api/v1/reports/trial-balance/").status_code == 403


def test_every_ledger_line_opens_its_document(accountant, director):
    mj = manual.create(
        accountant,
        lines=[
            LineInput(acc("6220"), debit="25000.00", division=div("WS")),
            LineInput(acc("2170"), credit="25000.00"),
        ],
        narration="Accrue repairs",
    )
    manual.approve(director, manual.submit(accountant, mj))
    body = (
        as_user(director)
        .get(f"/api/v1/reports/general-ledger/?account={acc('2170').pk}&from={MONTH_START}")
        .json()
    )
    (line,) = body["accounts"][0]["lines"]
    assert line["source_page"] == f"/journals/manual/{mj.pk}"
    entry = as_user(accountant).get(f"/api/v1/journal/{line['entry']['id']}/").json()
    assert entry["source_page"] == f"/journals/manual/{mj.pk}"


def test_the_exports(books, director):
    client = as_user(director)
    tb_xlsx = client.get("/api/v1/reports/trial-balance/?export=xlsx&compare=month")
    assert tb_xlsx.status_code == 200
    rows = list(load_workbook(io.BytesIO(tb_xlsx.content)).active.iter_rows(values_only=True))
    assert rows[-1][0] == "Total" and rows[-1][3] == rows[-1][4] == D("1165750")
    bs = client.get("/api/v1/reports/balance-sheet/?export=xlsx")
    rows = list(load_workbook(io.BytesIO(bs.content)).active.iter_rows(values_only=True))
    assert rows[-1][0] == "Total equity"  # no summed foot line on a balance sheet
    assert ("Total assets", 1162750) in [(r[0], r[1]) for r in rows]
    for url in ("balance-sheet", "trial-balance", "general-ledger", "profit-and-loss"):
        query = f"from={MONTH_START}&to={TODAY}&export=pdf"
        reply = client.get(f"/api/v1/reports/{url}/?{query}")
        assert reply.status_code == 200, url
        assert reply["Content-Type"] == "application/pdf"
