"""Labour categories (backlog P2B-16; owner, 5 Nov 2026): each employee is Shop and Office or
Wages Board; leave and short leave follow the category; maternity leave by the law as amended
in 2018."""

from datetime import date, time
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.masters.models import Shift
from apps.payroll import attendance, employees, leave, overtime
from apps.payroll.employees import EmployeeError
from apps.payroll.leave import LeaveError
from apps.payroll.models import Employee, LeaveType, OvertimeCheck

from .test_access import as_user, person
from .test_attendance import row, upload
from .test_employees import row as employee_row
from .test_employees import values, workbook

pytestmark = pytest.mark.django_db

OCT = date(2026, 10, 1)


@pytest.fixture
def hr():
    return person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)


def t(code):
    return LeaveType.objects.get(code=code)


def test_an_employee_is_shop_and_office_unless_hr_says_wages_board(hr):
    office = employees.create(hr, values())
    factory = employees.create(
        hr, values(number="E002", nic="198812345678", category="Wages Board")
    )
    assert (office.category, factory.category) == ("shop_office", "wages_board")
    with pytest.raises(EmployeeError, match="Shop and Office or Wages Board"):
        employees.create(hr, values(number="E003", nic="197712345678", category="casual"))
    body = as_user(hr).get(f"/api/v1/employees/{factory.pk}/").json()
    assert (body["category"], body["category_label"]) == ("wages_board", "Wages Board")
    listed = as_user(hr).get("/api/v1/employees/").json()
    assert {"value": "wages_board", "label": "Wages Board"} in listed["categories"]


def test_the_import_sets_the_category_and_a_blank_cell_keeps_it(hr):
    content = workbook([employee_row(category="Wages Board")])
    assert employees.import_workbook(hr, content, dry_run=False)["saved"] is True
    assert Employee.objects.get().category == "wages_board"
    content = workbook([employee_row(designation="Machinist")])  # no category given
    assert employees.import_workbook(hr, content, dry_run=False)["saved"] is True
    assert Employee.objects.get().category == "wages_board"


@pytest.mark.parametrize(
    "joined, year, annual, casual",
    [
        ("2025-02-10", 2025, "0", "5.0"),  # year of joining: no annual leave
        ("2025-02-10", 2026, "7", "7"),  # from the first full year: 7
        ("2025-11-30", 2026, "7", "7"),  # no quarter-of-joining rule
        ("2020-06-01", 2026, "7", "7"),
    ],
)
def test_wages_board_leave(hr, joined, year, annual, casual):
    e = employees.create(hr, values(join_date=joined, category="wages_board"))
    assert leave.entitlement(e, t("ANNUAL"), year) == D(annual)
    assert leave.entitlement(e, t("CASUAL"), year) == D(casual)


def test_the_leave_types_follow_the_owners_answers_and_the_law():
    assert t("CASUAL").name == "Casual and sick leave"
    annual = t("ANNUAL")
    assert (annual.days, annual.wb_rule, annual.wb_days) == (D(14), "after_joining", D(7))
    maternity = t("MATERNITY")
    assert (maternity.max_days, maternity.paid) == (D(84), True)


def test_hr_sets_the_wages_board_rule_and_a_limit_per_leave(hr):
    kind = leave.save_leave_type(
        hr,
        {
            "code": "STUDY",
            "name": "Study leave",
            "rule": "fixed",
            "days": "10",
            "wb_rule": "after_joining",
            "wb_days": "5",
            "max_days": "2",
        },
    )
    assert (kind.wb_rule, kind.wb_days, kind.max_days) == ("after_joining", D(5), D(2))
    with pytest.raises(LeaveError, match="keep a balance"):
        leave.save_leave_type(hr, {"wb_rule": "unlimited"}, kind, "x")
    kind.refresh_from_db()
    with pytest.raises(LeaveError, match="above 0"):
        leave.save_leave_type(hr, {"max_days": "0"}, kind, "x")
    kind.refresh_from_db()
    leave.save_leave_type(hr, {"wb_days": ""}, kind, "Same as Shop and Office")
    kind.refresh_from_db()
    assert kind.wb_days is None
    e = employees.create(hr, values(join_date="2020-01-15"))
    leave.grant_year(hr, 2026)
    with pytest.raises(LeaveError, match="at most 2.0 working days at a time"):
        leave.record(hr, e, kind, "2026-03-02", "2026-03-04")
    leave.record(hr, e, kind, "2026-03-02", "2026-03-03")
    body = as_user(hr).get("/api/v1/leave-types/").json()
    study = next(x for x in body["results"] if x["code"] == "STUDY")
    assert (study["wb_rule"], study["wb_days"], study["max_days"]) == ("after_joining", None, "2.0")


def test_maternity_leave_is_at_most_84_working_days_at_a_time(hr):
    e = employees.create(hr, values(join_date="2020-01-15"))
    with pytest.raises(LeaveError, match="84.0 working days"):
        leave.record(hr, e, t("MATERNITY"), "2026-01-05", "2026-04-30")
    taken = leave.record(hr, e, t("MATERNITY"), "2026-01-05", "2026-04-10")
    assert taken.days <= 84


@pytest.fixture
def two_people(hr):
    Shift.objects.create(
        code="DX", name="Day test", start_time=time(8), end_time=time(17), break_minutes=60
    )
    office = employees.create(hr, values(join_date="2024-01-15"))
    factory = employees.create(
        hr,
        values(number="E002", nic="198812345678", join_date="2024-01-15", category="wages_board"),
    )
    late = {"shift": "DX", "time_in": "08:30"}
    rows = []
    for number in ("E001", "E002"):
        rows += [row(1, number=number, **late), row(2, number=number, **late)]
    upload(hr, rows)
    return office, factory


def test_short_leave_is_paid_for_shop_and_office_and_unpaid_for_wages_board(hr, two_people):
    office, factory = two_people
    assert overtime.work_out(office, OCT, 0).unpaid_short_leaves == 0
    figures = overtime.work_out(factory, OCT, 0)
    assert (figures.short_leaves, figures.unpaid_short_leaves) == (2, 2)
    # A rule that pays Wages Board short leave too.
    paid = {"effective_from": "2026-10", "short_leave_paid_wb": True, "reason": "Paid"}
    overtime.add_rule(hr, "WS", paid)
    assert overtime.work_out(factory, OCT, 0).unpaid_short_leaves == 0


def test_the_checked_month_keeps_the_unpaid_short_leaves(hr, two_people):
    _, factory = two_people
    director = person("director@sml.lk", "director", all_divisions=True)
    attendance.confirm(hr, "WS", "2026-10")
    body = as_user(director).get("/api/v1/overtime/?division=WS&month=2026-10").json()
    line = next(r for r in body["rows"] if r["employee"]["number"] == "E002")
    assert (line["unpaid_short_leaves"], line["category"]) == (2, "wages_board")
    overtime.check(director, "WS", "2026-10", [factory.pk])
    kept = OvertimeCheck.objects.get()
    assert kept.unpaid_short_leaves == 2
    with pytest.raises(DatabaseError), transaction.atomic():
        OvertimeCheck.objects.filter(pk=kept.pk).update(unpaid_short_leaves=0)
