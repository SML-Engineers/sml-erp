"""Pay structure: earnings and deductions marked for EPF and APIT, and each employee's amounts
dated from a month, never changed (backlog P2B-02)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError, IntegrityError
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.payroll import employees, pay
from apps.payroll.models import PayComponent, PayRate
from apps.payroll.pay import PayError

from .test_access import as_user, person
from .test_employees import values

pytestmark = pytest.mark.django_db

D = Decimal


def first_of_next_month() -> date:
    today = timezone.localdate()
    return (today.replace(day=28) + timedelta(days=4)).replace(day=1)


@pytest.fixture
def hr():
    return person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def kamal(hr):
    return employees.create(hr, values(join_date="2024-01-15"))


def c(code):
    return PayComponent.objects.get(code=code)


def test_the_starting_components_are_loaded_without_the_old_relief_allowance():
    assert c("BASIC").epf_liable and c("BASIC").apit_taxable
    assert c("WELFARE").kind == "deduction"
    # Ended 31 March 2025: part of the basic wage now (Acts No. 9 and 10 of 2025).
    assert not PayComponent.objects.filter(name__icontains="relief").exists()


def test_hr_adds_and_changes_a_component(hr):
    meal = pay.save_component(
        hr, {"code": "meal", "name": "Meal allowance", "kind": "earning", "apit_taxable": True}
    )
    assert (meal.code, meal.epf_liable, meal.apit_taxable) == ("MEAL", False, True)
    with pytest.raises(PayError, match="reason"):
        pay.save_component(hr, {"epf_liable": True}, meal)
    meal = pay.save_component(hr, {"epf_liable": True}, meal, "Accountant confirmed")
    assert meal.epf_liable
    assert AuditEvent.objects.filter(event="pay_component_changed").exists()
    with pytest.raises(PayError, match="never change"):
        pay.save_component(hr, {"kind": "deduction"}, meal, "wrong")
    with pytest.raises(PayError, match="taken"):
        pay.save_component(hr, {"code": "MEAL", "name": "Again", "kind": "earning"})


def test_a_deduction_never_counts_for_epf_or_apit(hr):
    with pytest.raises(PayError, match="deduction"):
        pay.save_component(
            hr, {"code": "INS", "name": "Insurance", "kind": "deduction", "epf_liable": True}
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        PayComponent.objects.filter(code="WELFARE").update(apit_taxable=True)


def test_components_are_never_deleted_and_their_code_never_changes():
    with pytest.raises(DatabaseError), transaction.atomic():
        PayComponent.objects.filter(code="UNION").delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        PayComponent.objects.filter(code="UNION").update(code="UNION2")


def test_only_hr_keeps_components(director):
    response = as_user(director).post(
        "/api/v1/pay-components/", {"code": "X", "name": "X", "kind": "earning"}, format="json"
    )
    assert response.status_code == 403
    assert as_user(director).get("/api/v1/pay-components/").json()["can_manage"] is False


def test_a_raise_starts_on_its_month_and_earlier_months_keep_the_old_amount(hr, kamal):
    pay.add_rate(hr, kamal, c("BASIC"), "2024-01", "60000", "Joined")
    pay.add_rate(hr, kamal, c("TRAVEL"), "2024-01", "5000", "Joined")
    pay.add_rate(hr, kamal, c("WELFARE"), "2024-01", "250", "Joined")
    pay.add_rate(hr, kamal, c("BASIC"), "2025-04-01", "66000.50", "Annual increment")
    old = {x.component.code: x.amount for x in pay.amounts_on(kamal, date(2025, 3, 31))}
    new = {x.component.code: x.amount for x in pay.amounts_on(kamal, date(2025, 4, 1))}
    assert old == {"BASIC": D("60000.00"), "TRAVEL": D("5000.00"), "WELFARE": D("250.00")}
    assert new["BASIC"] == D("66000.50")
    totals = pay.totals(pay.amounts_on(kamal, date(2025, 4, 1)))
    assert totals == {
        "earnings": D("71000.50"),
        "deductions": D("250.00"),
        "net": D("70750.50"),
        "epf_earnings": D("66000.50"),
        "apit_earnings": D("71000.50"),
    }


def test_zero_ends_a_component(hr, kamal):
    with pytest.raises(PayError, match="no Travelling"):
        pay.add_rate(hr, kamal, c("TRAVEL"), "2024-01", "0", "Not paid")
    pay.add_rate(hr, kamal, c("TRAVEL"), "2024-01", "5000", "Joined")
    pay.add_rate(hr, kamal, c("TRAVEL"), "2025-01", "0", "Company van now")
    assert pay.amounts_on(kamal, date(2025, 1, 1)) == []


@pytest.mark.parametrize(
    "month, amount, reason, message",
    [
        ("2026-12-15", "1", "x", "1st of a month"),
        ("Dec", "1", "x", "for example"),
        ("2023-12", "1", "x", "before the employee joined"),
        ("2024-02", "-5", "x", "0 or more"),
        ("2024-02", "12.345", "x", "2 decimal places"),
        ("2024-02", "abc", "x", "a number"),
        ("2024-02", "100", "", "reason"),
    ],
)
def test_wrong_amounts_are_refused(hr, kamal, month, amount, reason, message):
    with pytest.raises(PayError, match=message):
        pay.add_rate(hr, kamal, c("BASIC"), month, amount, reason)


def test_one_amount_per_component_and_month(hr, kamal):
    pay.add_rate(hr, kamal, c("BASIC"), "2024-01", "60000", "Joined")
    with pytest.raises(PayError, match="already has an amount"):
        pay.add_rate(hr, kamal, c("BASIC"), "2024-01", "61000", "Mistake")


def test_an_amount_in_force_is_never_changed_or_withdrawn(hr, kamal):
    rate = pay.add_rate(hr, kamal, c("BASIC"), "2024-01", "60000", "Joined")
    with pytest.raises(PayError, match="taken effect"):
        pay.withdraw_rate(hr, rate, "Mistake")
    with pytest.raises(DatabaseError), transaction.atomic():
        PayRate.objects.filter(pk=rate.pk).update(amount=D("1"))
    with pytest.raises(DatabaseError), transaction.atomic():
        PayRate.objects.filter(pk=rate.pk).delete()
    with pytest.raises(IntegrityError), transaction.atomic():
        PayRate.objects.create(
            employee=kamal,
            component=c("TRAVEL"),
            effective_from=date(2024, 3, 15),
            amount=D("1"),
            reason="x",
            created_by=hr,
        )


def test_a_future_amount_can_be_withdrawn_with_a_reason(hr, kamal):
    rate = pay.add_rate(hr, kamal, c("BASIC"), first_of_next_month(), "70000", "Promotion")
    with pytest.raises(PayError, match="reason"):
        pay.withdraw_rate(hr, rate, "")
    response = as_user(hr).delete(
        f"/api/v1/employees/{kamal.pk}/pay/{rate.pk}/", {"reason": "Not approved"}, format="json"
    )
    assert response.status_code == 200, response.json()
    assert not PayRate.objects.filter(pk=rate.pk).exists()
    assert AuditEvent.objects.filter(event="pay_amount_withdrawn", reason="Not approved").exists()


def test_a_leaver_or_an_unused_component_gets_no_new_amount(hr, kamal):
    old = pay.save_component(hr, {"is_active": False}, c("INCENTIVE"), "Not paid any more")
    with pytest.raises(PayError, match="no longer used"):
        pay.add_rate(hr, kamal, old, "2024-01", "100", "x")
    employees.leave(hr, kamal, date(2026, 6, 30), "Resigned")
    with pytest.raises(PayError, match="has left"):
        pay.add_rate(hr, kamal, c("BASIC"), "2024-01", "100", "x")


def test_hr_and_the_director_see_the_pay_and_only_hr_enters_it(hr, director, kamal):
    url = f"/api/v1/employees/{kamal.pk}/pay/"
    entry = {"component": "basic", "month": "2024-01", "amount": "60000", "reason": "Joined"}
    response = as_user(hr).post(url, entry, format="json")
    assert response.status_code == 201, response.json()
    body = as_user(director).get(url).json()
    assert body["current"][0]["amount"] == "60000.00"
    assert body["totals"]["net"] == "60000.00"
    assert body["can_edit"] is False
    assert (
        as_user(director).post(url, entry | {"month": "2025-01"}, format="json").status_code == 403
    )
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    assert as_user(accountant).get(url).status_code == 403


def test_hr_of_another_division_cannot_enter_pay(kamal):
    im_hr = person("hr-im@sml.lk", "hr_payroll_officer", divisions=["IM"])
    with pytest.raises(PayError, match="divisions"):
        pay.add_rate(im_hr, kamal, c("BASIC"), "2024-01", "60000", "Joined")
    assert as_user(im_hr).get(f"/api/v1/employees/{kamal.pk}/pay/").status_code == 404
