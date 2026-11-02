"""Recurring journals and accruals reversed next month (backlog P2-02)."""

import calendar
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting import manual, recurring
from apps.accounting.manual import LineInput
from apps.accounting.models import (
    Account,
    AccountingPeriod,
    JournalEntry,
    ManualJournal,
    RecurringJournal,
)
from apps.accounting.services import AccountingError
from apps.core.models import Division, Notification

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def acc(number):
    return Account.objects.get(number=number)


def rent(amount="150000.00"):
    """Monthly factory rent accrued: Dr Rent (WS), Cr Accrued expenses."""
    return [
        LineInput(acc("6220"), debit=amount, division=Division.objects.get(code="WS")),
        LineInput(acc("2170"), credit=amount),
    ]


def values(**extra):
    base = {
        "name": "Factory rent",
        "narration": "Accrue factory rent",
        "frequency": "monthly",
        "day_of_month": 31,
        "start_date": TODAY,
        "reverse_next_month": True,
    }
    return recurring.Values(**(base | extra))


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


# --- The schedule ------------------------------------------------------------------------------


def test_the_schedule_keeps_the_last_day_and_the_quarters():
    t = RecurringJournal(frequency="monthly", day_of_month=31, start_date=date(2026, 1, 15))
    assert recurring.first_on_or_after(t, date(2026, 1, 1)) == date(2026, 1, 31)
    assert recurring.first_on_or_after(t, date(2026, 2, 1)) == date(2026, 2, 28)
    assert recurring.first_on_or_after(t, date(2026, 4, 1)) == date(2026, 4, 30)
    q = RecurringJournal(frequency="quarterly", day_of_month=15, start_date=date(2026, 1, 20))
    assert recurring.first_on_or_after(q, date(2026, 1, 1)) == date(2026, 4, 15)
    assert recurring.first_on_or_after(q, date(2026, 5, 1)) == date(2026, 7, 15)


# --- Keeping templates --------------------------------------------------------------------------


def test_the_accountant_keeps_a_balanced_template(accountant, director):
    t = recurring.save(accountant, None, values(), rent())
    assert t.next_date == month_end(TODAY)
    assert [(x.account.number, str(x.debit), str(x.credit)) for x in t.lines.all()] == [
        ("6220", "150000.00", "0.00"),
        ("2170", "0.00", "150000.00"),
    ]
    with pytest.raises(AccountingError, match="Only the Accountant"):
        recurring.save(director, None, values(), rent())
    with pytest.raises(AccountingError, match="does not balance"):
        recurring.save(accountant, None, values(), rent()[:1] + [rent("1.00")[1]])
    with pytest.raises(AccountingError, match="1 to 28, or the last day"):
        recurring.save(accountant, None, values(day_of_month=30), rent())
    with pytest.raises(AccountingError, match="end date"):
        recurring.save(accountant, None, values(end_date=TODAY - timedelta(days=1)), rent())


# --- Making the drafts --------------------------------------------------------------------------


def test_a_due_template_makes_a_draft_for_its_owner(accountant):
    t = recurring.save(accountant, None, values(), rent())
    first = t.next_date
    assert recurring.make_due(first - timedelta(days=1)) == 0
    assert recurring.make_due(first) == 1
    mj = ManualJournal.objects.get()
    assert (mj.status, mj.entry_date, mj.created_by, mj.recurring) == (
        "draft",
        first,
        accountant,
        t,
    )
    assert mj.narration == f"Accrue factory rent ({first:%b %Y})"
    assert mj.reverse_on == first + timedelta(days=1)  # the first of the next month
    assert manual.totals(mj) == (Decimal("150000.00"), Decimal("150000.00"))
    assert Notification.objects.filter(user=accountant, event="journal_ready").exists()
    t.refresh_from_db()
    assert t.next_date == month_end(first + timedelta(days=1))
    assert not JournalEntry.objects.exists()  # nothing posted without approval


def test_missed_dates_are_caught_up_and_closed_months_skipped(accountant):
    t = recurring.save(accountant, None, values(reverse_next_month=False), rent())
    first = t.next_date
    second = month_end(first + timedelta(days=1))
    third = month_end(second + timedelta(days=1))
    AccountingPeriod.objects.update_or_create(
        month=second.replace(day=1), defaults={"is_closed": True}
    )
    assert recurring.make_due(third) == 2  # the first and third; the closed second skipped
    assert sorted(ManualJournal.objects.values_list("entry_date", flat=True)) == [first, third]
    assert Notification.objects.filter(user=accountant, title__contains="was not made").exists()


def test_a_template_stops_after_its_end_date(accountant):
    t = recurring.save(accountant, None, values(end_date=month_end(TODAY)), rent())
    later = month_end(month_end(TODAY) + timedelta(days=1))
    assert recurring.make_due(later) == 1
    t.refresh_from_db()
    assert t.is_active is False


# --- Accruals reversed next month ------------------------------------------------------------


def test_an_approved_accrual_is_reversed_on_the_first_of_next_month(accountant, director):
    t = recurring.save(accountant, None, values(), rent())
    recurring.make_due(t.next_date)
    mj = manual.submit(accountant, ManualJournal.objects.get())
    mj = manual.approve(director, mj)
    assert manual.reverse_due(mj.reverse_on - timedelta(days=1)) == 0
    assert manual.reverse_due(mj.reverse_on) == 1
    reversal = JournalEntry.objects.get(reversal_of=mj.journal_entry)
    assert (reversal.entry_date, reversal.posted_by) == (mj.reverse_on, director)
    assert manual.reverse_due(mj.reverse_on) == 0  # never twice


def test_any_manual_journal_can_be_an_accrual(accountant):
    mj = manual.create(
        accountant,
        lines=rent(),
        entry_date=TODAY,
        narration="Accrue electricity",
        reverse_next_month=True,
    )
    assert mj.reverse_on == month_end(TODAY) + timedelta(days=1)
    mj = manual.save(accountant, mj, lines=rent(), reverse_next_month=False)
    assert mj.reverse_on is None


# --- API ----------------------------------------------------------------------------------------


def test_the_api(accountant, director):
    body = {
        "name": "Factory rent",
        "narration": "Accrue factory rent",
        "frequency": "monthly",
        "day_of_month": 31,
        "start_date": TODAY.isoformat(),
        "reverse_next_month": True,
        "lines": [
            {"account": acc("6220").pk, "debit": "150000.00", "division": "WS"},
            {"account": acc("2170").pk, "credit": "150000.00"},
        ],
    }
    made = as_user(accountant).post("/api/v1/recurring-journals/", body, format="json")
    assert made.status_code == 201, made.json()
    assert made.json()["next_date"] == month_end(TODAY).isoformat()
    pk = made.json()["id"]
    assert as_user(director).get("/api/v1/recurring-journals/").status_code == 200
    assert (
        as_user(director).post("/api/v1/recurring-journals/", body, format="json").status_code
        == 403
    )
    off = as_user(accountant).post(f"/api/v1/recurring-journals/{pk}/active/", {"active": False})
    assert off.json()["is_active"] is False
