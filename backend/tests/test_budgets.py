# ruff: noqa: F811 - the fixtures of test_journal are imported and used by name
"""Budgets by account, division and month, approved by the Director, and budget against
actual in the profit and loss (backlog P2-22)."""

import io
from datetime import date
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from apps.accounting import budgets
from apps.accounting.budgets import BudgetError, LineInput
from apps.accounting.models import Budget, BudgetLine

from .test_access import as_user, person
from .test_journal import acc, accountant, cost, director, div, sale  # noqa: F401

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
THIS_MONTH = TODAY.replace(day=1)
D = Decimal


def this_year() -> int:
    """The year this financial year starts in (the start month is a company setting)."""
    return budgets.year_start_of(TODAY).year


def plan(accountant, rows, budget=None):
    """A draft with `rows` of (account number, division, amount) for this month."""
    budget = budget or budgets.start(accountant, this_year())
    return budgets.save_lines(
        accountant,
        budget,
        [LineInput(acc(a), div(d), THIS_MONTH, D(v)) for a, d, v in rows],
    )


def approved(accountant, director, rows, budget=None):
    budget = budgets.submit(accountant, plan(accountant, rows, budget))
    return budgets.approve(director, budget, "agreed")


def test_the_financial_year_starts_in_april():
    assert budgets.year_start_of(date(2027, 3, 31)) == date(2026, 4, 1)
    assert budgets.year_start_of(date(2027, 4, 1)) == date(2027, 4, 1)
    year = budgets.months(date(2027, 4, 1))
    assert (year[0], year[-1], len(year)) == (date(2027, 4, 1), date(2028, 3, 1), 12)
    assert budgets.label(date(2027, 4, 1)) == "2027-28"


def test_the_director_approves_and_the_profit_and_loss_compares(accountant, director):
    budget = approved(accountant, director, [("4010", "WS", "1200.00"), ("6220", "WS", "500")])
    assert (budget.status, budget.version) == ("approved", 1)
    sale(accountant, "1000.00", "WS")
    cost(accountant, "400.00", "WS")

    planned = budgets.budgeted(THIS_MONTH, TODAY)
    assert planned == {acc("4010").pk: D("1200.00"), acc("6220").pk: D("-500.00")}
    url = f"/api/v1/reports/profit-and-loss/?from={THIS_MONTH}&to={TODAY}"
    body = as_user(accountant).get(url).json()
    rows = {r["account"]["number"]: r for r in body["rows"]}
    # Sales LKR 200 below budget; repairs LKR 100 under budget, which is better.
    assert (rows["4010"]["budget"], rows["4010"]["difference"], rows["4010"]["percent"]) == (
        "1200.00",
        "-200.00",
        "-16.7",
    )
    assert (rows["6220"]["amount"], rows["6220"]["budget"], rows["6220"]["difference"]) == (
        "-400.00",
        "-500.00",
        "100.00",
    )
    assert rows["6220"]["percent"] == "20.0"
    assert (body["profit"], body["budget_profit"], body["profit_difference"]) == (
        "600.00",
        "700.00",
        "-100.00",
    )
    other = as_user(accountant).get(url + "&division=IM").json()
    assert other["has_budget"] is False and "budget" not in (other["rows"] or [{}])[0]


def test_no_one_approves_their_own_budget(accountant):
    budget = budgets.submit(accountant, plan(accountant, [("4010", "WS", "100")]))
    with pytest.raises(BudgetError):
        budgets.approve(accountant, budget)
    assert Budget.objects.get(pk=budget.pk).status == "awaiting_approval"


def test_an_approved_budget_never_changes(accountant, director):
    budget = approved(accountant, director, [("4010", "WS", "100")])
    with pytest.raises(BudgetError, match="Only a draft"):
        plan(accountant, [("4010", "WS", "999")], budget)
    with transaction.atomic(), pytest.raises(DatabaseError, match="only while it is a draft"):
        BudgetLine.objects.filter(budget=budget).update(amount=999)
    with transaction.atomic(), pytest.raises(DatabaseError, match="never changes"):
        Budget.objects.filter(pk=budget.pk).update(notes="changed")
    with (
        transaction.atomic(),
        pytest.raises(DatabaseError, match="never deleted|only while it is a draft"),
    ):
        Budget.objects.filter(pk=budget.pk).delete()


def test_a_revision_starts_from_the_approved_one_and_replaces_it(accountant, director):
    first = approved(accountant, director, [("4010", "WS", "100")])
    revision = budgets.start(accountant, this_year(), "Second half reforecast")
    assert revision.version == 2
    assert list(revision.lines.values_list("amount", flat=True)) == [D("100.00")]
    with pytest.raises(BudgetError, match="already has a version"):
        budgets.start(accountant, this_year())
    # Until it is approved, the profit and loss uses the approved version.
    plan(accountant, [("4010", "WS", "150")], revision)
    assert budgets.budgeted(THIS_MONTH, TODAY) == {acc("4010").pk: D("100.00")}
    approved(accountant, director, [("4010", "WS", "150")], revision)
    assert Budget.objects.get(pk=first.pk).status == "replaced"
    assert budgets.budgeted(THIS_MONTH, TODAY) == {acc("4010").pk: D("150.00")}


def test_returned_goes_back_to_draft_and_rejected_is_final(accountant, director):
    budget = budgets.submit(accountant, plan(accountant, [("4010", "WS", "100")]))
    budget = budgets.send_back(director, budget, "Sales too low")
    assert budget.status == "draft"
    budget = budgets.submit(accountant, plan(accountant, [("4010", "WS", "130")], budget))
    budget = budgets.reject(director, budget, "Not this year")
    assert budget.status == "rejected"
    with transaction.atomic(), pytest.raises(DatabaseError, match="never changes"):
        Budget.objects.filter(pk=budget.pk).update(status="draft")
    assert budgets.start(accountant, this_year()).version == 2  # a new version can be prepared


def test_what_a_budget_line_can_be(accountant):
    budget = budgets.start(accountant, this_year())
    with pytest.raises(BudgetError, match="not an income or cost account"):
        plan(accountant, [("1010", "WS", "100")], budget)
    outside = date(this_year() + 1, budgets.start_month(), 1)
    with pytest.raises(BudgetError, match="is not in the"):
        budgets.save_lines(accountant, budget, [LineInput(acc("4010"), div("WS"), outside, D(1))])
    with pytest.raises(BudgetError, match="to the cent"):
        plan(accountant, [("4010", "WS", "1.005")], budget)
    with pytest.raises(BudgetError, match="no amounts"):
        budgets.submit(accountant, budget)
    with pytest.raises(BudgetError, match="Only the Accountant"):
        budgets.start(person("clerk@sml.lk", "clerk", all_divisions=True), this_year())


def _workbook(rows) -> bytes:
    book = Workbook()
    for row in rows:
        book.active.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_the_budget_is_imported_from_excel(accountant):
    budget = budgets.start(accountant, this_year())
    first, second = budgets.months(budget.year_start)[:2]
    content = _workbook(
        [
            ["SML Engineers budget"],
            ["Account", "Account name", "Division", f"{first:%b %Y}", second, "Total"],
            ["4010", "Sales", "WS", 1000, "2,500.50", 3500.5],
            [6220, "Repairs", "im", None, 300.25, None],
            ["", "Rent", "", None, None, None],  # nothing budgeted: skipped
        ]
    )
    budgets.import_file(accountant, budget, content)
    got = sorted(
        (x.account.number, x.division.code, x.month, x.amount)
        for x in budget.lines.select_related("account", "division")
    )
    assert got == [
        ("4010", "WS", first, D("1000.00")),
        ("4010", "WS", second, D("2500.50")),
        ("6220", "IM", second, D("300.25")),
    ]
    # The export comes back in the same layout.
    sheet = load_workbook(io.BytesIO(budgets.export_workbook(budget))).active
    assert [c.value for c in sheet[1]][:4] == [
        "Account",
        "Account name",
        "Division",
        f"{first:%b %Y}",
    ]
    again = budgets.parse(budget, budgets.export_workbook(budget))
    assert len(again) == 3


def test_an_import_with_a_wrong_row_saves_nothing(accountant):
    budget = plan(accountant, [("4010", "WS", "100")])
    first = budgets.months(budget.year_start)[0]
    content = _workbook(
        [
            ["Account", "Division", f"{first:%b %Y}"],
            ["4010", "WS", 500],
            ["9999", "WS", 10],
            ["6220", "XX", 10],
            ["6220", "WS", "ten"],
        ]
    )
    with pytest.raises(BudgetError) as refused:
        budgets.import_file(accountant, budget, content)
    text = str(refused.value)
    assert "Row 3: no active income or cost account 9999" in text
    assert "Row 4: give an active division code" in text
    assert "Row 5:" in text and "is not an amount" in text
    assert list(budget.lines.values_list("amount", flat=True)) == [D("100.00")]


def test_the_screens_api(accountant, director):
    api = as_user(accountant)
    made = api.post("/api/v1/budgets/", {"year": this_year()}, format="json")
    assert made.status_code == 201, made.data
    pk = made.data["id"]
    assert made.data["can_edit"] and len(made.data["months"]) == 12
    month = THIS_MONTH.isoformat()[:7]
    saved = api.put(
        f"/api/v1/budgets/{pk}/",
        {
            "notes": "First budget",
            "rows": [{"account": acc("4010").pk, "division": "WS", "amounts": {month: "1,000"}}],
        },
        format="json",
    )
    assert saved.status_code == 200, saved.data
    assert saved.data["rows"][0]["amounts"] == {month: "1000.00"}
    assert api.post(f"/api/v1/budgets/{pk}/submit/").status_code == 200
    boss = as_user(director)
    assert boss.get(f"/api/v1/budgets/{pk}/").data["can_approve"] is True
    done = boss.post(f"/api/v1/budgets/{pk}/approve/", {"comment": "ok"}, format="json")
    assert done.status_code == 200, done.data
    assert done.data["status"] == "approved"
    assert api.get(f"/api/v1/budgets/{pk}/export/").status_code == 200
    clerk = as_user(person("clerk@sml.lk", "clerk", all_divisions=True))
    assert clerk.get("/api/v1/budgets/").status_code == 403
