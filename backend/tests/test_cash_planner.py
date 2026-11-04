# ruff: noqa: F811 - the fixtures of test_export_invoices are imported and used by name
"""Cash flow planner: the bank balance projected for 13 weeks (backlog P2-25)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting import journal, planner
from apps.accounting.journal import Line
from apps.accounting.models import (
    Account,
    CashPlanItem,
    JournalEntry,
    RecurringJournal,
    RecurringJournalLine,
)
from apps.core.models import Division

from .test_access import as_user, person
from .test_export_invoices import (  # noqa: F401 - fixtures used by name
    accountant,
    buyer,
    director,
    executive,
    invoice,
    order,
    setup,
    stores,
)

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
D = Decimal


def acc(number):
    return Account.objects.get(number=number)


@pytest.fixture
def cash(accountant):
    """LKR 100,000 in cash since yesterday."""
    journal.post(
        accountant,
        entry_date=TODAY - timedelta(days=1),
        narration="Capital",
        lines=[
            Line(account=acc("1010"), debit="100000.00"),
            Line(
                account=Account.objects.get(system_role="opening_balance_equity"),
                credit="100000.00",
            ),
        ],
    )


def test_a_what_if_changes_the_projection_and_is_never_posted(accountant, cash):
    item = planner.add_what_if(
        accountant,
        description="New CNC machine",
        on_date=TODAY + timedelta(days=10),
        amount="150,000.00",
        money_in=False,
    )
    assert item.amount == D("-150000.00")
    plan = planner.projection(accountant)
    assert len(plan["days"]) == 91 and len(plan["weeks"]) == 13
    assert plan["opening"] == D("100000.00") and plan["closing"] == D("-50000.00")
    assert plan["lowest"] == {"amount": D("-50000.00"), "day": TODAY + timedelta(days=10)}
    assert plan["weeks"][1]["out"] == D("150000.00")
    switched_off = planner.projection(accountant, without={item.pk})
    assert switched_off["closing"] == D("100000.00")
    assert not JournalEntry.objects.filter(narration__icontains="CNC").exists()


def test_recurring_payments_from_the_bank_are_projected(accountant, cash):
    rent = RecurringJournal.objects.create(
        name="Factory rent",
        narration="Rent",
        frequency="monthly",
        day_of_month=TODAY.day,
        start_date=TODAY,
        next_date=TODAY,
        created_by=accountant,
    )
    RecurringJournalLine.objects.create(
        recurring=rent,
        line_no=1,
        account=acc("6220"),
        division=Division.objects.get(code="WS"),
        debit="20000.00",
    )
    RecurringJournalLine.objects.create(
        recurring=rent, line_no=2, account=acc("1010"), credit="20000.00"
    )
    flows = [f for f in planner.projection(accountant)["flows"] if f.kind == "recurring"]
    assert flows[0].day == TODAY and flows[0].amount == D("-20000.00")
    assert len(flows) in (3, 4)  # each month within the 13 weeks
    assert all(f.label == "Factory rent" for f in flows)


def test_what_customers_owe_comes_in_on_its_due_date(accountant, invoice):
    flows = [f for f in planner.projection(accountant)["flows"] if f.kind == "receivable"]
    (expected,) = flows
    assert expected.amount == D("750000.00")
    assert expected.day == max(TODAY, invoice.due_date)
    assert expected.link == f"/tax-invoices/{invoice.pk}"


def test_only_the_accountant_adds_what_ifs(accountant):
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    with pytest.raises(planner.AccountingError, match="Only the Accountant"):
        planner.add_what_if(clerk, description="x", on_date=TODAY, amount="1", money_in=True)
    with pytest.raises(planner.AccountingError, match="not nil"):
        planner.add_what_if(accountant, description="x", on_date=TODAY, amount="0", money_in=True)


def test_the_planner_api(accountant, cash):
    api = as_user(accountant)
    added = api.post(
        "/api/v1/cash-planner/what-ifs/",
        {
            "description": "Loan from the bank",
            "on_date": (TODAY + timedelta(days=3)).isoformat(),
            "amount": "50000",
            "direction": "in",
        },
        format="json",
    )
    assert added.status_code == 201, added.data
    assert added.data["closing"] == "150000.00"
    (item,) = added.data["what_ifs"]
    assert added.data["can_plan"] is True
    without = api.get(f"/api/v1/cash-planner/?without={item['id']}")
    assert without.data["closing"] == "100000.00"
    removed = api.delete(f"/api/v1/cash-planner/what-ifs/{item['id']}/")
    assert removed.status_code == 200 and not CashPlanItem.objects.exists()
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get("/api/v1/cash-planner/").status_code == 403
