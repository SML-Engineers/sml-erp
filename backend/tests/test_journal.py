"""Journal and accounting periods (backlog P0-16, spec 3)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import journal, services
from apps.accounting.journal import Line
from apps.accounting.models import Account, AccountingPeriod, DetailType, JournalEntry, JournalLine
from apps.accounting.services import AccountingError
from apps.core.models import AuditEvent, Division

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
LAST_MONTH = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)


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


def sale(user, amount, division="WS", on=TODAY, account="4010"):
    """Cash sale: debit cash, credit sales (with the division)."""
    return journal.post(
        user,
        entry_date=on,
        narration=f"Cash sale {division}",
        lines=[
            Line(account=acc("1010"), debit=amount),
            Line(account=acc(account), credit=amount, division=div(division)),
        ],
    )


def cost(user, amount, division="WS", on=TODAY, account="6220"):
    return journal.post(
        user,
        entry_date=on,
        narration=f"Repairs {division}",
        lines=[
            Line(account=acc(account), debit=amount, division=div(division)),
            Line(account=acc("1010"), credit=amount),
        ],
    )


def check_deferred():
    """Fire the checks that otherwise run when the transaction commits."""
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


# --- Posting ----------------------------------------------------------------------------


def test_a_balanced_entry_is_posted_with_a_number(accountant):
    entry = sale(accountant, "115750.00")
    assert entry.number == f"JV{TODAY:%y%m}0001"
    lines = list(entry.lines.order_by("line_no"))
    assert [(line.debit, line.credit) for line in lines] == [
        (Decimal("115750.00"), Decimal("0")),
        (Decimal("0"), Decimal("115750.00")),
    ]
    # the accounts and the division are now used: codes fixed, no deleting
    assert services.is_in_use(acc("4010"))
    assert div("WS").first_used_at is not None
    with pytest.raises(AccountingError, match="make it inactive instead"):
        services.delete_account(accountant, acc("4010"), "tidy up")
    assert AuditEvent.objects.filter(event="journal_posted").exists()
    check_deferred()  # the database agrees that it balances


def test_an_unbalanced_entry_is_refused(accountant):
    with pytest.raises(AccountingError, match="does not balance: debits 100.00, credits 99.99"):
        journal.post(
            accountant,
            entry_date=TODAY,
            narration="Wrong",
            lines=[
                Line(account=acc("1010"), debit="100.00"),
                Line(account=acc("4010"), credit="99.99", division=div("WS")),
            ],
        )
    assert not JournalEntry.objects.exists()


def test_the_database_refuses_an_unbalanced_entry(accountant):
    with pytest.raises(DatabaseError, match="does not balance"), transaction.atomic():
        entry = JournalEntry.objects.create(
            number="TEST1",
            entry_date=TODAY,
            source_type="manual",
            narration="Bypassing the service",
            posted_by=accountant,
        )
        JournalLine.objects.create(entry=entry, line_no=1, account=acc("1010"), debit=100)
        JournalLine.objects.create(entry=entry, line_no=2, account=acc("1100"), credit=99)
        check_deferred()
    with pytest.raises(DatabaseError, match="at least two lines"), transaction.atomic():
        JournalEntry.objects.create(
            number="TEST2",
            entry_date=TODAY,
            source_type="manual",
            narration="No lines",
            posted_by=accountant,
        )
        check_deferred()
    with pytest.raises(DatabaseError), transaction.atomic():
        entry = JournalEntry.objects.create(
            number="TEST3",
            entry_date=TODAY,
            source_type="manual",
            narration="x",
            posted_by=accountant,
        )
        JournalLine.objects.create(entry=entry, line_no=1, account=acc("1010"), debit=-5)


@pytest.mark.parametrize(
    "debit, credit, why",
    [
        (1.5, "1.50", "not floating point"),
        ("-10.00", "0", "negative"),
        ("10.005", "0", "to the cent"),
        ("10.00", "10.00", "either a debit or a credit"),
        ("0", "0", "either a debit or a credit"),
        ("abc", "0", "not a number"),
    ],
)
def test_amounts_are_exact_positive_and_on_one_side(accountant, debit, credit, why):
    with pytest.raises(AccountingError, match=why):
        journal.post(
            accountant,
            entry_date=TODAY,
            narration="x",
            lines=[
                Line(account=acc("1010"), debit=debit, credit=credit),
                Line(account=acc("1100"), credit="10.00"),
            ],
        )


def test_posted_entries_are_never_changed_or_deleted(accountant):
    entry = sale(accountant, "500.00")
    line = entry.lines.first()
    for attempt in (
        lambda: JournalEntry.objects.filter(pk=entry.pk).update(narration="changed"),
        lambda: JournalEntry.objects.filter(pk=entry.pk).delete(),
        lambda: JournalLine.objects.filter(pk=line.pk).update(debit=Decimal("600.00")),
        lambda: JournalLine.objects.filter(pk=line.pk).delete(),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            attempt()


def test_an_income_or_expense_line_needs_a_division(accountant):
    with pytest.raises(AccountingError, match="needs a division"):
        journal.post(
            accountant,
            entry_date=TODAY,
            narration="No division",
            lines=[
                Line(account=acc("6220"), debit="10.00"),
                Line(account=acc("1010"), credit="10.00"),
            ],
        )
    entry = sale(accountant, "10.00")
    with pytest.raises(DatabaseError, match="needs a division"), transaction.atomic():
        JournalLine.objects.create(entry=entry, line_no=9, account=acc("6220"), debit=10)
    # balance sheet lines may go without a division
    assert entry.lines.get(account=acc("1010")).division is None


def test_inactive_and_merged_accounts_take_no_postings(accountant):
    services.update_account(accountant, acc("6230"), {"is_active": False}, "not used")
    with pytest.raises(AccountingError, match="Vehicle repairs is inactive"):
        cost(accountant, "10.00", account="6230")
    services.update_account(accountant, acc("6230"), {"is_active": True})
    services.merge_accounts(accountant, acc("6230"), acc("6220"), "one account")
    with pytest.raises(AccountingError, match="was merged into Building repairs"):
        cost(accountant, "10.00", account="6230")
    entry = sale(accountant, "10.00")
    with pytest.raises(DatabaseError, match="inactive or merged"), transaction.atomic():
        JournalLine.objects.create(
            entry=entry, line_no=9, account=acc("6230"), debit=10, division=div("WS")
        )


# --- Periods ----------------------------------------------------------------------------


def test_posting_into_a_closed_period_is_refused(accountant, director):
    cost(accountant, "50.00", on=LAST_MONTH)
    journal.set_closed(director, LAST_MONTH, True)
    with pytest.raises(AccountingError, match=f"period {LAST_MONTH:%Y-%m} is closed"):
        cost(accountant, "50.00", on=LAST_MONTH + timedelta(days=3))
    with pytest.raises(DatabaseError, match="is closed"), transaction.atomic():
        JournalEntry.objects.create(
            number="TEST4",
            entry_date=LAST_MONTH,
            source_type="manual",
            narration="Bypassing the service",
            posted_by=accountant,
        )
    # reopening (with a reason) allows posting again
    journal.set_closed(director, LAST_MONTH, False, reason="late supplier invoice")
    assert cost(accountant, "50.00", on=LAST_MONTH).entry_date == LAST_MONTH
    assert AuditEvent.objects.filter(event="period_reopened").exists()


def test_only_the_director_closes_and_reopens_periods(accountant, director):
    with pytest.raises(AccountingError, match="Only the Director"):
        journal.set_closed(accountant, LAST_MONTH, True)
    with pytest.raises(AccountingError, match="has ended"):
        journal.set_closed(director, TODAY, True)
    journal.set_closed(director, LAST_MONTH, True)
    with pytest.raises(AccountingError, match="already closed"):
        journal.set_closed(director, LAST_MONTH, True)
    with pytest.raises(AccountingError, match="reason"):
        journal.set_closed(director, LAST_MONTH, False)
    url = f"/api/v1/accounting-periods/{LAST_MONTH:%Y-%m}/reopen/"
    response = as_user(accountant).post(url, {"reason": "x"}, format="json")
    assert response.status_code == 400 and "Only the Director" in response.json()["detail"]
    response = as_user(director).post(url, {"reason": "audit adjustment"}, format="json")
    assert response.status_code == 200, response.json()
    months = response.json()["months"]
    assert len(months) == 12
    assert next(m for m in months if m["month"] == f"{LAST_MONTH:%Y-%m}")["is_closed"] is False
    assert (
        as_user(director)
        .post(f"/api/v1/accounting-periods/{LAST_MONTH:%Y-%m}/delete/", {}, format="json")
        .status_code
        == 404
    )
    assert AccountingPeriod.objects.get(month=LAST_MONTH).changed_by == director


def test_the_type_of_an_account_with_entries_in_a_closed_period_is_fixed(accountant, director):
    cost(accountant, "75.00", on=LAST_MONTH, account="6100")
    other = DetailType.objects.get(account_type="cost_of_goods_sold", name="Factory overheads")
    journal.set_closed(director, LAST_MONTH, True)
    with pytest.raises(AccountingError, match="entries in a closed period"):
        services.update_account(
            accountant, acc("6100"), {"account_type": "cost_of_goods_sold", "detail_type": other}
        )
    with pytest.raises(DatabaseError, match="closed period"), transaction.atomic():
        Account.objects.filter(number="6100").update(
            account_type="cost_of_goods_sold", detail_type=other
        )
    # once the period is reopened, the type can be corrected
    journal.set_closed(director, LAST_MONTH, False, reason="reclassify electricity")
    services.update_account(
        accountant, acc("6100"), {"account_type": "cost_of_goods_sold", "detail_type": other}
    )


# --- Reversal ---------------------------------------------------------------------------


def test_a_reversal_is_the_mirror_entry_linked_to_the_original(accountant):
    original = cost(accountant, "1200.00")
    reversal = journal.reverse(accountant, original, reason="entered twice")
    assert reversal.reversal_of == original
    assert reversal.narration == f"Reversal of {original.number}: entered twice"

    def pairs(e):
        return sorted(
            (line.account.number, line.division_id, line.debit, line.credit)
            for line in e.lines.all()
        )

    mirrored = sorted((a, d, c, b) for a, d, b, c in pairs(original))
    assert pairs(reversal) == mirrored
    assert pairs(original) == pairs(JournalEntry.objects.get(pk=original.pk))  # unchanged
    totals = journal.profit_and_loss(TODAY, TODAY)
    assert totals.get(acc("6220").pk, Decimal("0")) == Decimal("0")
    with pytest.raises(AccountingError, match="already been reversed"):
        journal.reverse(accountant, original, reason="again")
    with pytest.raises(AccountingError, match="itself a reversal"):
        journal.reverse(accountant, reversal, reason="undo")
    with pytest.raises(AccountingError, match="reason"):
        journal.reverse(accountant, cost(accountant, "5.00"), reason="")


def test_an_entry_in_a_closed_period_is_reversed_in_an_open_one(accountant, director):
    original = cost(accountant, "300.00", on=LAST_MONTH)
    journal.set_closed(director, LAST_MONTH, True)
    reversal = journal.reverse(accountant, original, reason="wrong supplier")
    assert reversal.entry_date == TODAY
    with pytest.raises(AccountingError, match="is closed"):
        journal.reverse(accountant, cost(accountant, "1.00"), reason="x", on_date=LAST_MONTH)


def test_the_accountant_reverses_through_the_api_and_the_director_only_views(accountant, director):
    original = cost(accountant, "80.00")
    url = f"/api/v1/journal/{original.pk}/reverse/"
    assert as_user(director).post(url, {"reason": "x"}, format="json").status_code == 403
    response = as_user(accountant).post(url, {"reason": "wrong amount"}, format="json")
    assert response.status_code == 201, response.json()
    assert response.json()["reversal_of"]["number"] == original.number
    detail = as_user(director).get(f"/api/v1/journal/{original.pk}/").json()
    assert detail["reversed_by"]["number"] == response.json()["number"]
    assert detail["amount"] == "80.00"
    assert [line["debit"] for line in detail["lines"]] == ["80.00", "0.00"]
    assert detail["lines"][0]["division"] == "WS"
    listed = as_user(director).get(f"/api/v1/journal/?account={acc('6220').pk}").json()
    assert {row["number"] for row in listed} == {original.number, response.json()["number"]}
    assert all(row["amount"] == "80.00" for row in listed)
    admin = person("admin@sml.lk", "system_admin", all_divisions=True)
    assert as_user(admin).get("/api/v1/journal/").status_code == 403


# --- Profit and loss by division ---------------------------------------------------------


def test_profit_and_loss_by_division_adds_up_to_the_company_total(accountant):
    sale(accountant, "115750.00", "WS")
    sale(accountant, "48000.50", "IM", account="4020")
    cost(accountant, "12500.25", "WS")
    cost(accountant, "3000.00", "IM", account="6210")
    cost(accountant, "9999.99", "HO", account="6600")
    sale(accountant, "1.00", "WS", on=TODAY - timedelta(days=400))  # outside the range
    start, end = TODAY.replace(day=1), TODAY
    company = journal.profit_and_loss(start, end)
    by_division = [journal.profit_and_loss(start, end, div(code)) for code in ("WS", "IM", "HO")]
    assert sum(company.values()) == sum(sum(d.values()) for d in by_division)
    assert sum(company.values()) == Decimal("138250.26")
    for account_id, amount in company.items():
        assert amount == sum(d.get(account_id, Decimal("0")) for d in by_division)
    ws = by_division[0]
    assert ws[acc("4010").pk] == Decimal("115750.00") and ws[acc("6220").pk] == Decimal("-12500.25")


def test_entries_of_a_merged_account_are_reported_under_the_remaining_one(accountant):
    cost(accountant, "300.00", account="6230")
    cost(accountant, "200.00", account="6220")
    before = journal.profit_and_loss(TODAY, TODAY)
    services.merge_accounts(accountant, acc("6230"), acc("6220"), "one repairs account")
    after = journal.profit_and_loss(TODAY, TODAY)
    assert after == {acc("6220").pk: Decimal("-500.00")}
    assert sum(after.values()) == sum(before.values())


def test_the_profit_and_loss_report_api(accountant):
    sale(accountant, "1000.00", "WS")
    cost(accountant, "400.00", "IM", account="6210")
    url = f"/api/v1/reports/profit-and-loss/?from={TODAY:%Y-%m-01}&to={TODAY.isoformat()}"
    body = as_user(accountant).get(url).json()
    assert body["profit"] == "600.00"
    ws = as_user(accountant).get(url + "&division=ws").json()
    assert ws["division"] == "WS" and ws["profit"] == "1000.00"
    assert ws["rows"][0]["account"]["number"] == "4010"
    assert as_user(accountant).get(url + "&division=IM").json()["profit"] == "-400.00"
    assert as_user(accountant).get(url + "&division=XX").status_code == 400
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get(url).status_code == 403
