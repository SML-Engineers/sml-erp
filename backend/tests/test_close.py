# ruff: noqa: F811 - the fixtures of test_journal are imported and used by name
"""Month-end checklist and year-end close (backlog P2-23)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import budgets, close, journal, reports
from apps.accounting import services as chart
from apps.accounting.close import CloseError
from apps.accounting.models import Account, DetailType, MonthEndTick, YearEndClose
from apps.masters import banking

from .test_access import as_user, person
from .test_journal import LAST_MONTH, acc, accountant, cost, director, div, sale  # noqa: F401

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
D = Decimal


def last_year():
    """The financial year before this one: all its months have ended."""
    this = budgets.year_start_of(TODAY)
    return budgets.year_start_of(this - timedelta(days=1))


def bank(accountant):
    return banking.create_account(
        accountant,
        code="com-lkr",
        kind="current",
        name="Commercial Bank LKR",
        bank_name="Commercial Bank",
        account_number="1000234599",
        currency="LKR",
        ledger_account=chart.create_account(
            accountant,
            name="Commercial Bank LKR",
            account_type="bank",
            detail_type=DetailType.objects.get(name="Current account"),
            number="1035",
        ).pk,
    )


def items(month):
    return {i.key: i for i in close.checklist(month)}


# --- Month end -------------------------------------------------------------------------------


def test_a_month_is_closed_only_when_its_checklist_is_done(accountant, director):
    bank(accountant)
    got = items(LAST_MONTH)
    assert not got["bank_reconciliations"].done
    assert "COM-LKR" in got["bank_reconciliations"].detail
    assert got["depreciation"].done and got["revaluation"].done and got["journals"].done
    assert not got["accruals"].done
    with pytest.raises(CloseError, match="Still to do: Bank accounts reconciled"):
        close.close_month(director, LAST_MONTH)

    close.tick(accountant, LAST_MONTH, "bank_reconciliations", "No statement yet; checked online")
    close.tick(accountant, LAST_MONTH, "accruals", "Electricity accrued, JNL-0004")
    got = items(LAST_MONTH)
    assert got["accruals"].done and got["accruals"].note == "Electricity accrued, JNL-0004"
    assert got["accruals"].ticked_by == accountant.full_name
    period = close.close_month(director, LAST_MONTH)
    assert period.is_closed


def test_ticks_need_a_note_and_the_accountant_and_never_change(accountant, director):
    with pytest.raises(CloseError, match="Say what was done"):
        close.tick(accountant, LAST_MONTH, "accruals", "  ")
    with pytest.raises(CloseError, match="Only the Accountant"):
        close.tick(person("clerk@sml.lk", "clerk", all_divisions=True), LAST_MONTH, "accruals", "x")
    with pytest.raises(CloseError, match="Unknown"):
        close.tick(accountant, LAST_MONTH, "coffee", "x")
    close.tick(accountant, LAST_MONTH, "accruals", "Done")
    with transaction.atomic(), pytest.raises(DatabaseError):
        MonthEndTick.objects.update(note="changed")
    with pytest.raises(CloseError, match="Only the Director"):
        close.close_month(accountant, LAST_MONTH)


def test_the_checklist_api_and_closing_through_it(accountant, director):
    month = f"{LAST_MONTH:%Y-%m}"
    api = as_user(accountant)
    got = api.get(f"/api/v1/month-end/{month}/")
    assert got.status_code == 200, got.data
    assert got.data["can_tick"] and not got.data["can_close"] and not got.data["ready"]
    refused = as_user(director).post(
        f"/api/v1/accounting-periods/{month}/close/", {}, format="json"
    )
    assert refused.status_code == 400 and "Still to do" in refused.json()["detail"]
    ticked = api.post(
        f"/api/v1/month-end/{month}/tick/", {"item": "accruals", "note": "None"}, format="json"
    )
    assert ticked.status_code == 201, ticked.data
    assert ticked.data["ready"] is True
    closed = as_user(director).post(f"/api/v1/accounting-periods/{month}/close/", {}, format="json")
    assert closed.status_code == 200, closed.json()


# --- Year end --------------------------------------------------------------------------------


def close_months(director, start):
    for month in budgets.months(start):
        journal.set_closed(director, month, True)


def test_the_year_s_profit_goes_to_retained_earnings_on_the_next_year_s_first_day(
    accountant, director
):
    start = last_year()
    on = start + timedelta(days=70)
    sale(accountant, "1000.00", "WS", on=on)
    cost(accountant, "400.00", "WS", on=on)
    cost(accountant, "50.00", "IM", on=on, account="6210")
    with pytest.raises(CloseError, match="Close every month of the year first"):
        close.close_year(director, start)
    close_months(director, start)
    with pytest.raises(CloseError, match="Only the Director"):
        close.close_year(accountant, start)

    done = close.close_year(director, start)
    next_start = budgets.year_start_of(TODAY)
    assert done.profit == D("550.00")
    assert done.journal_entry.entry_date == next_start
    lines = sorted(
        (x.account.system_role or x.account.number, x.division.code, x.debit, x.credit)
        for x in done.journal_entry.lines.select_related("account", "division")
    )
    assert lines == [
        ("4010", "WS", D("1000.00"), 0),
        ("6210", "IM", 0, D("50.00")),
        ("6220", "WS", 0, D("400.00")),
        ("retained_earnings", "IM", D("50.00"), 0),
        ("retained_earnings", "WS", 0, D("600.00")),
    ]
    # The closed year's profit and loss reads as before; the new year starts from nil.
    year_end = next_start - timedelta(days=1)
    assert sum(journal.profit_and_loss(start, year_end).values()) == D("550.00")
    assert journal.profit_and_loss(next_start, next_start) == {}
    retained = Account.objects.get(system_role="retained_earnings")
    assert reports.balances(next_start)[retained.pk] == D("-550.00")
    with pytest.raises(CloseError, match="closed already"):
        close.close_year(director, start)


def test_reopening_the_year_reverses_the_close(accountant, director):
    start = last_year()
    sale(accountant, "1000.00", "WS", on=start + timedelta(days=10))
    close_months(director, start)
    done = close.close_year(director, start)
    with pytest.raises(CloseError, match="reopen the year first"):
        close.reopen_month(director, start, "late invoice")
    with pytest.raises(CloseError, match="Give a reason"):
        close.reopen_year(director, start, "")
    with transaction.atomic(), pytest.raises(DatabaseError, match="never changes"):
        YearEndClose.objects.filter(pk=done.pk).update(profit=0)
    with transaction.atomic(), pytest.raises(DatabaseError, match="never deleted"):
        YearEndClose.objects.filter(pk=done.pk).delete()

    reopened = close.reopen_year(director, start, "Auditors' adjustment")
    assert reopened.reopened and reopened.reopen_entry.reversal_of == done.journal_entry
    retained = Account.objects.get(system_role="retained_earnings")
    assert retained.pk not in reports.balances(budgets.year_start_of(TODAY))
    close.reopen_month(director, start, "late invoice")  # now allowed
    journal.set_closed(director, start, True)
    again = close.close_year(director, start)
    assert again.profit == D("1000.00") and YearEndClose.objects.count() == 2


def test_the_year_end_api(accountant, director):
    start = last_year()
    sale(accountant, "1000.00", "WS", on=start + timedelta(days=10))
    close_months(director, start)
    got = as_user(accountant).get("/api/v1/year-end/", {"year": start.year})
    assert got.status_code == 200, got.data
    assert got.data["open_months"] == [] and got.data["closed"] is False
    refused = as_user(accountant).post(f"/api/v1/year-end/{start.year}/close/")
    assert refused.status_code == 400 and "Only the Director" in refused.json()["detail"]
    done = as_user(director).post(f"/api/v1/year-end/{start.year}/close/")
    assert done.status_code == 200, done.json()
    assert done.json()["closed"] is True and done.json()["history"][0]["profit"] == "1000.00"
