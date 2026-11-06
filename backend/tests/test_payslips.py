"""Payslips (backlog P2B-08): from an approved payroll, printed by HR or the Director, emailed
to employees with an email address, locked with the employee's NIC number."""

from datetime import date

import pytest
from django.core import mail

from apps.core.models import SentEmail
from apps.payroll import employees, payroll, payslips
from apps.payroll.models import Employee, PayrollLine

from .test_access import as_user, person
from .test_attendance import upload
from .test_document_email import admin, finance, memory_storage  # noqa: F401
from .test_employees import values
from .test_payroll import (  # noqa: F401
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


@pytest.fixture
def approved(hr, director, kamal):  # noqa: F811
    Employee.objects.filter(pk=kamal.pk).update(email="kamal@example.com")
    nimal = employees.create(
        hr, values(number="E002", nic="198812345678", join_date="2024-01-15", email="")
    )
    approve_pay(hr, director, nimal, PAY[:1])
    upload(hr, present("E001", working_days()) + present("E002", working_days()))
    close_month(hr, director, kamal, nimal)
    run = payroll.prepare(hr, "WS", "2026-10")
    payroll.submit(hr, run)
    payroll.approve(director, run)
    run.refresh_from_db()
    return run


def test_hr_and_the_director_print_payslips(hr, director, approved):  # noqa: F811
    url = f"/api/v1/payroll/{approved.pk}/payslips/"
    response = as_user(hr).get(url)
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "payslips-WS-2026-10.pdf" in response["Content-Disposition"]
    one = as_user(director).get(url + f"?employee={approved.lines.first().employee_id}")
    assert one.status_code == 200 and "payslip-2026-10-E001.pdf" in one["Content-Disposition"]
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    refused = as_user(accountant).get(url)
    assert refused.status_code == 400 and "Only HR and the Director" in refused.json()["detail"]


def test_no_payslips_before_approval(hr, director, kamal):  # noqa: F811
    upload(hr, present("E001", working_days()))
    close_month(hr, director, kamal)
    run = payroll.prepare(hr, "WS", "2026-10")
    response = as_user(hr).get(f"/api/v1/payroll/{run.pk}/payslips/")
    assert response.status_code == 400 and "approved" in response.json()["detail"]


def test_payslips_are_emailed_locked_and_recorded(hr, director, approved, finance):  # noqa: F811
    response = as_user(hr).post(f"/api/v1/payroll/{approved.pk}/email-payslips/")
    assert response.status_code == 200, response.json()
    assert response.json() == {"sent": ["E001"], "failed": [], "no_email": ["E002"]}
    [message] = mail.outbox
    assert message.to == ["kamal@example.com"] and message.bcc == []  # no company copy
    assert "October 2026" in message.subject and "NIC number" in message.body
    name, content, kind = message.attachments[0]
    assert (name, kind) == ("payslip-2026-10-E001.pdf", "application/pdf")
    assert b"/Encrypt" in content  # locked
    record = SentEmail.objects.get(document_type="payslip")
    assert record.document_id == PayrollLine.objects.get(employee__number="E001").pk
    refused = as_user(director).post(f"/api/v1/payroll/{approved.pk}/email-payslips/")
    assert refused.status_code == 400 and "Only HR emails" in refused.json()["detail"]


def test_without_a_mailbox_nothing_is_sent(hr, approved):  # noqa: F811
    response = as_user(hr).post(f"/api/v1/payroll/{approved.pk}/email-payslips/")
    assert response.status_code == 400 and "not set up" in response.json()["detail"]


def test_year_to_date_runs_from_april(approved):
    assert payslips.year_start(date(2026, 10, 20)) == date(2026, 4, 1)
    assert payslips.year_start(date(2027, 3, 20)) == date(2026, 4, 1)
    assert payslips.year_start(date(2027, 4, 20)) == date(2027, 4, 1)
    line = approved.lines.get(employee__number="E001")
    ytd = payslips.year_to_date(line)
    assert (ytd.gross, ytd.net, ytd.months) == (line.gross, line.net, 1)
