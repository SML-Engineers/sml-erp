"""Gratuity (backlog P2B-19): settings by the Accountant approved by the Director, never less
than the Payment of Gratuity Act (half a month's wage per completed year after 5 years), and
each approved payroll's monthly provision."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.accounting.models import JournalLine
from apps.payroll import employees, gratuity, payroll
from apps.payroll.gratuity import GratuityError
from apps.payroll.models import GratuitySetting

from .test_access import as_user, person
from .test_attendance import upload
from .test_employees import values
from .test_payroll import (  # noqa: F401 - fixtures used by name
    PAY,
    approve_pay,
    close_month,
    director,
    hr,
    kamal,
    present,
    working_days,
)

pytestmark = pytest.mark.django_db
URL = "/api/v1/gratuity/"


@pytest.fixture
def accountant():
    return person("acc@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def senior(hr, director):  # noqa: F811
    """Joined on 15 January 2020: 6 completed years on 20 October 2026; wage 66,000 (basic +
    fixed allowance, the components in the day rate)."""
    e = employees.create(
        hr, values(number="E003", nic="197912345678", epf_no="9003", join_date="2020-01-15")
    )
    approve_pay(hr, director, e, PAY)
    return e


def test_the_act_without_settings(senior):
    assert gratuity.completed_years(date(2020, 1, 15), date(2026, 10, 20)) == 6
    assert gratuity.completed_years(date(2020, 1, 15), date(2025, 1, 14)) == 4
    assert gratuity.wage(senior, date(2026, 10, 1)) == D("66000")
    # Half a month's wage for each of 6 completed years.
    assert gratuity.liability(senior, date(2026, 10, 1), date(2026, 10, 20), D("66000")) == (
        6,
        D("99000.00") * 2,
    )
    # Not earned before 5 completed years.
    assert gratuity.liability(senior, date(2024, 10, 1), date(2024, 10, 20), D("66000")) == (
        4,
        D("0.00"),
    )


def test_each_approved_payroll_provides_for_it(hr, director, kamal, senior):  # noqa: F811
    upload(hr, present("E001", working_days()) + present("E003", working_days()))
    close_month(hr, director, kamal, senior)
    run = payroll.prepare(hr, "WS", "2026-10")
    line = run.lines.get(employee=senior)
    assert (line.gratuity_years, line.gratuity_liability) == (6, D("198000.00"))
    assert line.gratuity_charge == D("198000.00")  # nothing provided before
    assert run.lines.get(employee=kamal).gratuity_liability == 0  # 2 years
    payroll.submit(hr, run)
    payroll.approve(director, run)
    run.refresh_from_db()
    posted = {
        x.account.system_role: (x.debit, x.credit)
        for x in JournalLine.objects.filter(entry=run.journal_entry).select_related("account")
    }
    assert posted["gratuity_expense"] == (D("198000.00"), D("0.00"))
    assert posted["gratuity_provision"] == (D("0.00"), D("198000.00"))
    body = as_user(hr).get(f"/api/v1/payroll/{run.pk}/").json()
    assert body["gratuity"] == {"liability": "198000.00", "provided": "198000.00"}
    # The next payroll provides only the change since this one.
    assert gratuity.provided(senior, date(2026, 11, 1)) == D("198000.00")
    assert gratuity.provided(senior, date(2026, 10, 1)) == D("0.00")


def test_the_accountant_enters_settings_and_the_director_approves(
    accountant,
    director,  # noqa: F811
    hr,  # noqa: F811
    senior,
):
    body = {
        "employee_id": senior.pk,
        "effective_from": "2026-11",
        "service_from": "2019-06-01",
        "months_per_year": "1",
        "after_years": "3",
        "reason": "Service with the related company counted, as agreed",
    }
    for changed, message in [
        ({"months_per_year": "0.4"}, "0.5 (the Act) to 3"),
        ({"after_years": "6"}, "0 to 5 completed years"),
        ({"service_from": "2021-01-01"}, "never later"),
        ({"effective_from": "2026-01"}, "or later"),
        ({"reason": ""}, "Give the reason"),
    ]:
        refused = as_user(accountant).post(URL, body | changed, format="json")
        assert refused.status_code == 400 and message in refused.json()["detail"], changed
    # HR has no say in gratuity settings: no Accounting area, or the service refuses.
    assert as_user(hr).post(URL, body, format="json").status_code in (400, 403)
    made = as_user(accountant).post(URL, body, format="json")
    assert made.status_code == 200, made.json()
    row = next(r for r in made.json()["results"] if r["number"] == "E003")
    assert row["by_act"] is True and row["waiting"]["months_per_year"] == "1.00"
    assert row["waiting"]["can_approve"] is False and row["waiting"]["can_withdraw"] is True
    again = as_user(accountant).post(URL, body, format="json")
    assert "already has settings waiting" in again.json()["detail"]
    setting = GratuitySetting.objects.get()
    with pytest.raises(GratuityError):
        gratuity.decide(accountant, setting.pk, "approve")
    seen = as_user(director).get(URL).json()["results"]
    assert next(r for r in seen if r["number"] == "E003")["waiting"]["can_approve"] is True
    done = as_user(director).post(f"{URL}settings/{setting.pk}/approve/")
    assert done.status_code == 200
    setting.refresh_from_db()
    assert setting.status == "approved"
    # From November: service from June 2019 (7 years), one month a year after 3 years.
    t = gratuity.terms(senior, date(2026, 11, 1))
    assert (t.service_from, t.months_per_year, t.after_years) == (date(2019, 6, 1), D("1"), 3)
    assert gratuity.liability(senior, date(2026, 11, 1), date(2026, 11, 20), D("66000")) == (
        7,
        D("462000.00"),
    )
    assert gratuity.terms(senior, date(2026, 10, 1)).setting is None  # earlier months: the Act
    with pytest.raises(DatabaseError), transaction.atomic():
        GratuitySetting.objects.filter(pk=setting.pk).update(months_per_year=D("2"))
    with pytest.raises(DatabaseError), transaction.atomic():
        GratuitySetting.objects.filter(pk=setting.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        GratuitySetting.objects.create(
            employee=senior,
            effective_from=date(2026, 12, 1),
            service_from=date(2020, 1, 15),
            months_per_year=D("0.25"),
            after_years=5,
            reason="Below the Act",
            created_by=accountant,
        )


def test_settings_may_be_withdrawn_or_rejected(accountant, director, senior):  # noqa: F811
    body = {"effective_from": "2026-11", "months_per_year": "0.75", "reason": "Staff policy"}
    first = gratuity.propose(accountant, senior, body)
    with pytest.raises(GratuityError, match="reason for withdrawing"):
        gratuity.decide(accountant, first.pk, "withdraw")
    gratuity.decide(accountant, first.pk, "withdraw", "Entered too early")
    second = gratuity.propose(accountant, senior, body)
    gratuity.decide(director, second.pk, "reject", "Keep the Act")
    assert list(GratuitySetting.objects.values_list("status", flat=True).order_by("id")) == [
        "withdrawn",
        "rejected",
    ]
    assert gratuity.terms(senior, date(2026, 11, 1)).setting is None
