"""Employee self-service (backlog P2B-11): an employee signed in sees only their own payslips,
contributions, APIT certificate, leave and attendance, and applies for leave, which their
section's supervisor or HR approves."""

import pytest

from apps.core.models import Division
from apps.masters.models import Section
from apps.payroll import employees, leave
from apps.payroll.models import Employee, Leave

from .test_access import as_user, person
from .test_employees import values
from .test_payroll import close_month, director, hr, kamal, present, working_days  # noqa: F401
from .test_payslips import approved  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/v1/my/"


@pytest.fixture
def me(hr, kamal):  # noqa: F811
    user = person("kamal@sml.lk", divisions=["WS"])
    employees.update(hr, kamal, {"user_email": "KAMAL@sml.lk"})
    return user


def test_hr_links_the_sign_in_by_email(hr, kamal, me):  # noqa: F811
    assert Employee.objects.get(pk=kamal.pk).user_id == me.pk
    body = as_user(hr).get(f"/api/v1/employees/{kamal.pk}/").json()
    assert body["user"]["email"] == "kamal@sml.lk"
    with pytest.raises(employees.EmployeeError, match="no active sign-in"):
        employees.update(hr, kamal, {"user_email": "nobody@sml.lk"})
    employees.update(hr, kamal, {"user_email": ""})
    assert Employee.objects.get(pk=kamal.pk).user_id is None


def test_without_a_link_nothing_is_shown():
    stranger = person("x@sml.lk", divisions=["WS"])
    body = as_user(stranger).get(URL).json()
    assert body["linked"] is False and "Ask HR" in body["detail"]


def test_an_employee_sees_their_own_payslips_and_certificate(hr, approved, me):  # noqa: F811
    body = as_user(me).get(URL).json()
    assert body["employee"]["number"] == "E001"
    [slip] = body["payslips"]
    assert (slip["month"], slip["net"], slip["epf_employer"]) == ("2026-10", "66850.00", "8100.00")
    pdf = as_user(me).get(f"{URL}payslips/{slip['id']}/")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    others = approved.lines.get(employee__number="E002")
    refused = as_user(me).get(f"{URL}payslips/{others.pk}/")
    assert refused.status_code == 400 and "no such payslip of yours" in refused.json()["detail"]
    certificate = as_user(me).get(f"{URL}apit-certificate/?year=2026")
    assert certificate["Content-Type"] == "application/pdf"
    assert as_user(me).get(f"{URL}apit-certificate/?year=2025").status_code == 400
    assert len(body["attendance"]["days"]) > 0 or body["attendance"]["from"]


def test_an_employee_applies_for_leave_and_withdraws_it(hr, me):  # noqa: F811
    leave.grant_year(hr, 2026)
    made = as_user(me).post(
        f"{URL}leave/",
        {"leave_type": "ANNUAL", "start": "2026-12-01", "end": "2026-12-02", "reason": "Trip"},
        format="json",
    )
    assert made.status_code == 201, made.json()
    applied = made.json()["leave"][0]
    assert (applied["status"], applied["days"], applied["can_withdraw"]) == ("applied", "2.0", True)
    annual = next(b for b in made.json()["balances"] if b["code"] == "ANNUAL")
    assert annual["pending"] == "2.0"
    bad = as_user(me).post(f"{URL}leave/", {"leave_type": "NOPAY", "start": "2026-12-03"})
    assert bad.status_code == 400 and "kind of leave" in bad.json()["detail"]
    gone = as_user(me).post(f"{URL}leave/{applied['id']}/withdraw/")
    assert gone.json()["leave"][0]["status"] == "cancelled"


def test_the_section_supervisor_approves_never_their_own(hr, kamal, me):  # noqa: F811
    section = Section.objects.create(
        code="SX",
        name="Test section",
        division=Division.objects.get(code="WS"),
        section_type="machining",
    )
    supervisor = person("sup@sml.lk", divisions=["WS"])
    section.supervisors.add(supervisor, me)
    employees.update(hr, kamal, {"section": "SX"})
    leave.grant_year(hr, 2026)
    as_user(me).post(f"{URL}leave/", {"leave_type": "CASUAL", "start": "2026-12-01"})
    x = Leave.objects.get(employee=kamal)
    assert as_user(me).get(URL).json()["to_approve"] == []  # not their own
    refused = as_user(me).post(f"/api/v1/my/team-leave/{x.pk}/approve/")
    assert refused.status_code == 400
    waiting = as_user(supervisor).get(URL).json()
    assert waiting["linked"] is False  # no employee record, but the applications are listed
    assert [a["id"] for a in waiting["to_approve"]] == [x.pk]
    done = as_user(supervisor).post(f"/api/v1/my/team-leave/{x.pk}/approve/")
    assert done.status_code == 200, done.json()
    assert Leave.objects.get(pk=x.pk).status == "approved"


def test_supervisors_see_applications_to_decide(hr, kamal, me):  # noqa: F811
    section = Section.objects.create(
        code="SY", name="Other", division=Division.objects.get(code="WS"), section_type="support"
    )
    boss = employees.create(
        hr, values(number="E009", full_name="Boss", nic="197512345678", join_date="2020-01-15")
    )
    boss_user = person("boss@sml.lk", divisions=["WS"])
    employees.update(hr, boss, {"user_email": "boss@sml.lk"})
    section.supervisors.add(boss_user)
    employees.update(hr, kamal, {"section": "SY"})
    leave.grant_year(hr, 2026)
    as_user(me).post(f"{URL}leave/", {"leave_type": "CASUAL", "start": "2026-12-01"})
    [application] = as_user(boss_user).get(URL).json()["to_approve"]
    assert application["employee"] == "E001 Kamal Perera"
    rejected = as_user(boss_user).post(
        f"/api/v1/my/team-leave/{application['id']}/reject/", {"reason": "Stock count"}
    )
    assert rejected.status_code == 200
    assert Leave.objects.get(pk=application["id"]).status == "rejected"
