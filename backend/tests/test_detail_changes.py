"""Employees ask to change their own details (backlog P2B-20): HR decides, never the employee
themselves; a new salary account still waits for the Director's check."""

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.payroll import detailchanges, employees
from apps.payroll.detailchanges import DetailChangeError
from apps.payroll.models import DetailChange, Employee

from .test_access import as_user, person
from .test_employees import values

pytestmark = pytest.mark.django_db
MY = "/api/v1/my/details/"
HR_URL = "/api/v1/detail-changes/"
BANK = {
    "bank_name": "Commercial Bank",
    "bank_branch": "Kandy",
    "account_name": "K Perera",
    "account_number": "8001234567",
}


@pytest.fixture
def hr():
    return person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def kamal(hr):
    return employees.create(hr, values(phone="0771234567"))


@pytest.fixture
def me(hr, kamal):
    user = person("kamal@sml.lk", divisions=["WS"])
    employees.update(hr, kamal, {"user_email": "kamal@sml.lk"})
    return user


def test_an_employee_asks_and_may_withdraw(me):
    body = as_user(me).get("/api/v1/my/").json()
    assert body["details"]["phone"] == "0771234567" and body["detail_requests"] == []
    same = as_user(me).post(MY, {"phone": "0771234567"}, format="json")
    assert same.status_code == 400 and "Nothing is different" in same.json()["detail"]
    bad = as_user(me).post(MY, {"email": "not-an-email"}, format="json")
    assert bad.status_code == 400 and "email address is not valid" in bad.json()["detail"]
    made = as_user(me).post(
        MY, {"phone": "0719998887", "address": " 12  Lake Road ", "note": "New SIM"}, format="json"
    )
    assert made.status_code == 201, made.json()
    [asked] = made.json()["detail_requests"]
    assert asked["status"] == "waiting" and asked["note"] == "New SIM"
    assert {c["field"]: c["after"] for c in asked["changes"]} == {
        "phone": "0719998887",
        "address": "12 Lake Road",
    }
    again = as_user(me).post(MY, {"phone": "0710000000"}, format="json")
    assert again.status_code == 400 and "already have a request waiting" in again.json()["detail"]
    gone = as_user(me).post(f"{MY}{asked['id']}/withdraw/")
    assert gone.json()["detail_requests"][0]["status"] == "withdrawn"
    assert Employee.objects.get(user=me).phone == "0771234567"


def test_hr_approves_and_the_record_changes(hr, me):
    detailchanges.ask(me, {"phone": "0719998887"})
    waiting = as_user(hr).get(HR_URL).json()["results"]
    assert [c["changes"][0]["before"] for c in waiting] == ["0771234567"]
    assert as_user(me).get(HR_URL).status_code == 403
    done = as_user(hr).post(f"{HR_URL}{waiting[0]['id']}/approve/")
    assert done.status_code == 200 and done.json()["results"] == []
    assert Employee.objects.get(user=me).phone == "0719998887"
    assert DetailChange.objects.get().status == "approved"


def test_a_new_salary_account_still_waits_for_the_directors_check(hr, director, me):
    change = detailchanges.ask(me, BANK, "Moved my account")
    detailchanges.decide(hr, change.pk, True)
    employee = Employee.objects.get(user=me)
    assert employee.account_number == "8001234567" and employee.bank_check_pending
    employees.check_bank(director, employee)
    assert not Employee.objects.get(user=me).bank_check_pending


def test_nobody_decides_their_own_request_or_checks_their_own_account(hr, director):
    own = employees.create(hr, values(number="E009", nic="198812345678", epf_no="9009"))
    employees.update(hr, own, {"user_email": "hr@sml.lk"})
    change = detailchanges.ask(hr, BANK)
    assert list(detailchanges.waiting(hr)) == []
    with pytest.raises(DetailChangeError, match="their own details"):
        detailchanges.decide(hr, change.pk, True)
    boss = employees.create(hr, values(number="E010", nic="197512345678", epf_no="9010"))
    employees.update(hr, boss, {"user_email": "director@sml.lk", **BANK}, reason="New account")
    with pytest.raises(employees.EmployeeError, match="their own salary account"):
        employees.check_bank(director, Employee.objects.get(pk=boss.pk))


def test_rejecting_needs_a_reason_and_decided_requests_never_change(hr, me):
    change = detailchanges.ask(me, {"email": "kamal@gmail.com"})
    refused = as_user(hr).post(f"{HR_URL}{change.pk}/reject/", {"reason": ""})
    assert refused.status_code == 400 and "reason for rejecting" in refused.json()["detail"]
    as_user(hr).post(f"{HR_URL}{change.pk}/reject/", {"reason": "Use the work email"})
    change.refresh_from_db()
    assert (change.status, change.decision_note) == ("rejected", "Use the work email")
    assert Employee.objects.get(user=me).email == ""
    with pytest.raises(DatabaseError), transaction.atomic():
        DetailChange.objects.filter(pk=change.pk).update(status="approved")
    with pytest.raises(DatabaseError), transaction.atomic():
        DetailChange.objects.filter(pk=change.pk).delete()
    with pytest.raises(DetailChangeError, match="already decided"):
        detailchanges.decide(hr, change.pk, True)


def test_an_old_request_never_overwrites_newer_details(hr, kamal, me):
    change = detailchanges.ask(me, {"phone": "0719998887"})
    employees.update(hr, Employee.objects.get(pk=kamal.pk), {"phone": "0112345678"})
    with pytest.raises(DetailChangeError, match="changed these details since"):
        detailchanges.decide(hr, change.pk, True)
    assert Employee.objects.get(pk=kamal.pk).phone == "0112345678"
