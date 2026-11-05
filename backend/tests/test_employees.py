"""Employee master: added and kept by HR, seen by HR and the Director only, bank accounts
checked by a second person, never deleted, and imported from Excel all or nothing
(backlog P2B-01)."""

import io
from datetime import date

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from openpyxl import Workbook, load_workbook

from apps.core.models import AuditEvent
from apps.payroll import employees
from apps.payroll.employees import COLUMNS, EmployeeError
from apps.payroll.models import Employee

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

URL = "/api/v1/employees/"


@pytest.fixture
def hr():
    return person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def values(**extra):
    return {
        "number": "E001",
        "full_name": "Kamal Perera",
        "nic": "199012345678",
        "division": "WS",
        "employment_type": "permanent",
        "join_date": "2024-01-15",
        "date_of_birth": "1990-05-01",
        "epf_no": "1234",
    } | extra


def add(hr, **extra):
    return employees.create(hr, values(**extra))


def test_hr_adds_an_employee_and_the_number_is_stored_in_capitals(hr):
    response = as_user(hr).post(URL, values(number="e001", nic="901234567v"), format="json")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert (body["number"], body["nic"], body["division"]) == ("E001", "901234567V", "WS")
    assert AuditEvent.objects.filter(event="employee_added").exists()


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"nic": "12345"}, "NIC"),
        ({"nic": "19901234567X"}, "NIC"),
        ({"full_name": ""}, "full name"),
        ({"join_date": ""}, "join date"),
        ({"join_date": "15th Jan"}, "not a date"),
        ({"employment_type": "freelance"}, "employment type"),
        ({"division": "XX"}, "divisions"),
        ({"email": "not-an-email"}, "email"),
        ({"confirmation_date": "2023-01-01"}, "before the join date"),
        ({"date_of_birth": "2015-01-01"}, "younger than 14"),
        ({"account_number": "!!"}, "account number"),
        ({"section": "NO-SUCH"}, "no section"),
    ],
)
def test_wrong_details_are_refused(hr, extra, message):
    with pytest.raises(EmployeeError, match=message):
        add(hr, **extra)


def test_the_nic_and_the_number_are_unique(hr):
    add(hr)
    with pytest.raises(EmployeeError, match="NIC"):
        add(hr, number="E002")
    with pytest.raises(EmployeeError, match="taken"):
        add(hr, nic="198812345678")


def test_the_employment_type_can_be_given_by_its_label(hr):
    assert add(hr, employment_type="On probation").employment_type == "probation"


def test_only_hr_and_the_director_see_employees(hr, director):
    add(hr)
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    clerk = person("clerk@sml.lk", "clerk", divisions=["WS"])
    assert as_user(hr).get(URL).json()["results"][0]["number"] == "E001"
    assert as_user(director).get(URL).json()["can_add"] is False
    # The Accountant sees payroll totals only, never personal details.
    assert as_user(accountant).get(URL).status_code == 403
    assert as_user(clerk).get(URL).status_code == 403
    assert employees.visible(accountant).count() == 0


def test_the_director_cannot_add_or_change_employees(hr, director):
    employee = add(hr)
    assert as_user(director).post(URL, values(number="E009"), format="json").status_code == 403
    response = as_user(director).patch(f"{URL}{employee.pk}/", {"phone": "1"}, format="json")
    assert response.status_code == 403


def test_hr_sees_only_their_divisions(hr):
    add(hr)
    add(hr, number="E002", nic="198812345678", division="IM")
    im_hr = person("hr-im@sml.lk", "hr_payroll_officer", divisions=["IM"])
    numbers = [r["number"] for r in as_user(im_hr).get(URL).json()["results"]]
    assert numbers == ["E002"]
    ws = Employee.objects.get(number="E001")
    assert as_user(im_hr).get(f"{URL}{ws.pk}/").status_code == 404
    with pytest.raises(EmployeeError, match="divisions"):
        employees.create(im_hr, values(number="E003", nic="197712345678"))


def test_the_employee_number_never_changes(hr):
    employee = add(hr)
    with pytest.raises(EmployeeError, match="never changes"):
        employees.update(hr, employee, {"number": "E999"})
    with pytest.raises(DatabaseError), transaction.atomic():
        Employee.objects.filter(pk=employee.pk).update(number="E999")


def test_employees_are_never_deleted_but_leave(hr):
    employee = add(hr)
    with pytest.raises(DatabaseError), transaction.atomic():
        Employee.objects.filter(pk=employee.pk).delete()
    with pytest.raises(EmployeeError, match="reason"):
        employees.leave(hr, employee, date(2026, 6, 30), "")
    with pytest.raises(EmployeeError, match="before the join date"):
        employees.leave(hr, employee, date(2020, 1, 1), "Resigned")
    response = as_user(hr).post(
        f"{URL}{employee.pk}/leave/",
        {"leaving_date": "2026-06-30", "reason": "Resigned"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    employee.refresh_from_db()
    assert (employee.is_active, employee.leaving_date) == (False, date(2026, 6, 30))
    with pytest.raises(EmployeeError, match="has left"):
        employees.update(hr, employee, {"phone": "077"})
    assert as_user(hr).get(URL).json()["results"] == []
    assert len(as_user(hr).get(f"{URL}?status=left").json()["results"]) == 1


def test_a_new_bank_account_waits_for_the_directors_check(hr, director):
    employee = add(hr, bank_name="Commercial Bank", account_number="8001234567")
    assert employee.bank_check_pending
    # The person who changed it cannot check it, nor can HR (no approve).
    with pytest.raises(EmployeeError, match="Director"):
        employees.check_bank(hr, employee)
    response = as_user(director).post(f"{URL}{employee.pk}/check-bank/")
    assert response.status_code == 200, response.json()
    employee.refresh_from_db()
    assert not employee.bank_check_pending
    with pytest.raises(EmployeeError, match="no bank account change"):
        employees.check_bank(director, employee)


def test_a_bank_change_needs_a_reason_and_a_new_check(hr, director):
    employee = add(hr, account_number="8001234567")
    employees.check_bank(director, employee)
    with pytest.raises(EmployeeError, match="reason"):
        employees.update(hr, employee, {"account_number": "8009999999"})
    employee = employees.update(hr, employee, {"account_number": "8009999999"}, "New account")
    assert employee.bank_check_pending
    assert AuditEvent.objects.filter(event="employee_changed", reason="New account").exists()
    # Changing something else does not need a check.
    employees.check_bank(director, employee)
    employee = employees.update(hr, employee, {"phone": "0771234567"})
    assert not employee.bank_check_pending


def test_nobody_checks_their_own_bank_change(director):
    both = person("both@sml.lk", "hr_payroll_officer", "director", all_divisions=True)
    employee = employees.create(both, values(account_number="8001234567"))
    with pytest.raises(EmployeeError, match="cannot check"):
        employees.check_bank(both, employee)
    employees.check_bank(director, employee)


def test_the_section_must_belong_to_the_division(hr):
    from apps.masters.models import Section

    section = Section.objects.filter(division__code="WS").first()
    if section is None:
        pytest.skip("no sections loaded")
    assert add(hr, section=section.code).section == section
    with pytest.raises(EmployeeError, match="no section"):
        add(hr, number="E002", nic="198812345678", division="IM", section=section.code)


# --- Excel ------------------------------------------------------------------------------------


def workbook(rows) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.append([label for _, label in COLUMNS])
    for row in rows:
        sheet.append([row.get(key) for key, _ in COLUMNS])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def row(**extra):
    return values(join_date=date(2024, 1, 15), date_of_birth=None, **extra)


def test_the_template_has_the_column_names(hr):
    response = as_user(hr).get(f"{URL}excel/?template=1")
    assert response.status_code == 200
    sheet = load_workbook(io.BytesIO(response.content)).active
    assert [c.value for c in sheet[1]] == [label for _, label in COLUMNS]


def test_exporting_everyones_details_needs_the_export_permission(hr, director):
    add(hr)
    response = as_user(hr).get(f"{URL}excel/")
    assert response.status_code == 200
    sheet = load_workbook(io.BytesIO(response.content)).active
    assert sheet["A2"].value == "E001"
    assert as_user(director).get(f"{URL}excel/").status_code == 403


def test_the_import_is_checked_first_and_then_saved(hr):
    content = workbook([row(), row(number="E002", nic="198812345678", division="IM")])
    result = employees.import_workbook(hr, content, dry_run=True)
    assert result == {"errors": [], "added": 2, "updated": 0, "saved": False}
    assert Employee.objects.count() == 0
    result = employees.import_workbook(hr, content, dry_run=False)
    assert (result["added"], result["saved"]) == (2, True)
    # A second import updates by employee number.
    content = workbook([row(designation="Machinist")])
    result = employees.import_workbook(hr, content, dry_run=False)
    assert (result["added"], result["updated"]) == (0, 1)
    assert Employee.objects.get(number="E001").designation == "Machinist"


def test_one_wrong_row_saves_nothing_and_every_error_is_listed(hr):
    content = workbook(
        [
            row(),
            row(number="E002", nic="bad"),
            row(number="E003", nic="197712345678", division="XX"),
            row(number="E001", nic="196612345678"),
        ]
    )
    result = employees.import_workbook(hr, content, dry_run=False)
    assert result["saved"] is False
    assert len(result["errors"]) == 3
    assert "Row 3" in result["errors"][0] and "NIC" in result["errors"][0]
    assert "appears twice" in result["errors"][2]
    assert Employee.objects.count() == 0


def test_a_file_that_is_not_excel_is_refused(hr):
    with pytest.raises(EmployeeError, match="not an Excel"):
        employees.import_workbook(hr, b"hello", dry_run=True)


def test_only_hr_imports(hr, director):
    refused = io.BytesIO(workbook([row()]))
    refused.name = "staff.xlsx"
    response = as_user(director).post(f"{URL}excel/", {"file": refused}, format="multipart")
    assert response.status_code == 403
    upload = io.BytesIO(workbook([row()]))
    upload.name = "staff.xlsx"
    response = as_user(hr).post(
        f"{URL}excel/", {"file": upload, "dry_run": "false"}, format="multipart"
    )
    assert response.status_code == 200, response.json()
    assert response.json()["added"] == 1
