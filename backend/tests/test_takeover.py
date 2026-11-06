"""Taking over from the old payroll (backlog P2B-14): pay settings and the year's figures to
date uploaded from the ERP's templates, the Director approving; a pay month run in both,
compared employee by employee and signed off by the Director."""

import io
from datetime import date
from decimal import Decimal as D

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from openpyxl import Workbook, load_workbook

from apps.payroll import employees, gratuity, payslips, returns, takeover
from apps.payroll.models import OpeningFigures, ParallelCheck, PayChange
from apps.payroll.takeover import TakeoverError

from .test_access import as_user
from .test_employees import values
from .test_payroll import director, hr, kamal  # noqa: F401 - fixtures used by name
from .test_payslips import approved  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/v1/payroll-takeover/"
OPENING_HEAD = [label for _, label in takeover.OPENING_COLUMNS]
COMPARE_HEAD = [
    "Employee no",
    "Name",
    "Gross pay",
    "EPF 8%",
    "EPF 12%",
    "ETF 3%",
    "APIT",
    "Net pay",
]


def book(head, rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(head)
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def opening_row(number="E001", last="2026-09", months=6, gratuity_provided=50000):
    # Gross, APIT taxable, APIT, EPF 8%, EPF 12%, ETF 3%, net, gratuity.
    return [number, last, months, 438000, 438000, 0, 32400, 48600, 12150, 400000, gratuity_provided]


def test_pay_settings_come_over_as_new_employees_for_the_director(hr):  # noqa: F811
    sunil = employees.create(hr, values(number="E005", nic="198512345678", epf_no="9005"))
    template = load_workbook(io.BytesIO(takeover.pay_template(hr))).active
    head = [c.value for c in template[1]]
    assert head[:2] == ["Employee no", "From pay month"] and "BASIC" in head
    assert template["A2"].value == "E005"

    good = book(
        ["Employee no", "From pay month", "BASIC", "FIXED"], [["E005", "2026-11", 55000, 5000]]
    )
    preview = takeover.import_pay(hr, good, dry_run=True)
    assert (preview["rows"], preview["saved"], preview["errors"]) == (1, False, [])
    assert not PayChange.objects.exists()

    bad = book(
        ["Employee no", "From pay month", "BASIC"],
        [["E005", "2026-11", 55000], ["E404", "2026-11", 1000]],
    )
    refused = takeover.import_pay(hr, bad, dry_run=False)
    assert refused["saved"] is False and "no employee E404" in refused["errors"][0]
    assert not PayChange.objects.exists()  # all or nothing
    with pytest.raises(TakeoverError, match="not pay components in use: BONUSX"):
        takeover.import_pay(hr, book(["Employee no", "From pay month", "BONUSX"], []), dry_run=True)

    response = as_user(hr).post(
        f"{URL}pay/",
        {"file": SimpleUploadedFile("pay.xlsx", good), "dry_run": "false"},
        format="multipart",
    )
    assert response.status_code == 200 and response.json()["saved"] is True
    change = PayChange.objects.get(employee=sunil)
    assert change.status == "awaiting" and change.is_new_employee
    assert {(x.component.code, x.amount) for x in change.lines.all()} == {
        ("BASIC", D("55000")),
        ("FIXED", D("5000")),
    }


def test_the_years_figures_to_date_count_once_the_director_approves(
    hr,  # noqa: F811
    director,  # noqa: F811
    approved,  # noqa: F811
):
    content = book(OPENING_HEAD, [opening_row()])
    preview = takeover.import_opening(hr, content, "ytd.xlsx", dry_run=True)
    assert (preview["employees"], preview["tax_year"], preview["errors"]) == (1, "2026", [])
    assert preview["totals"]["gross"] == "438000.00"
    # Months already paid here are refused.
    clash = takeover.import_opening(
        hr, book(OPENING_HEAD, [opening_row(last="2026-10", months=7)]), "x.xlsx", dry_run=True
    )
    assert "already in this payroll for pay month October 2026" in clash["errors"][0]
    two_years = takeover.import_opening(
        hr,
        book(OPENING_HEAD, [opening_row(), opening_row("E002", last="2026-02", months=11)]),
        "x.xlsx",
        dry_run=True,
    )
    assert "one year of assessment" in two_years["errors"][-1]

    response = as_user(hr).post(
        f"{URL}opening/",
        {"file": SimpleUploadedFile("ytd.xlsx", content), "dry_run": "false"},
        format="multipart",
    )
    assert response.status_code == 200 and response.json()["saved"] is True
    again = takeover.import_opening(hr, content, "ytd.xlsx", dry_run=True)
    assert "already has opening figures" in again["errors"][0]
    line = approved.lines.get(employee__number="E001")
    before = payslips.year_to_date(line)
    page = as_user(hr).get(URL).json()
    [batch] = page["batches"]
    assert batch["status"] == "awaiting" and batch["can_decide"] is False
    assert as_user(hr).post(f"{URL}opening/{batch['id']}/approve/").status_code == 400
    seen = as_user(director).get(URL).json()["batches"][0]
    assert seen["can_decide"] is True
    done = as_user(director).post(f"{URL}opening/{batch['id']}/approve/")
    assert done.status_code == 200 and done.json()["batches"][0]["status"] == "approved"

    after = payslips.year_to_date(line)
    assert after.gross == before.gross + D("438000") and after.months == before.months + 6
    assert after.epf_employee == before.epf_employee + D("32400")
    report = returns.apit_year(hr, 2026)
    row = next(r for r in report.rows if r[0] == "E001")
    assert row[3] == 7 and row[4] == D("438000") + line.apit_earnings
    assert any("old payroll" in n for n in report.notes)
    # The gratuity the old payroll provided, before the first payroll here.
    kamal_ = line.employee
    assert gratuity.provided(kamal_, date(2026, 10, 1)) == D("50000")
    with pytest.raises(DatabaseError), transaction.atomic():
        OpeningFigures.objects.update(gross=D("1"))


def test_a_month_run_in_both_is_compared_and_signed_off(hr, director, approved):  # noqa: F811
    lines = {x.employee.number: x for x in approved.lines.select_related("employee")}
    template = load_workbook(io.BytesIO(takeover.compare_template(hr, approved.pk))).active
    assert [c.value for c in template[1]] == COMPARE_HEAD
    assert sorted(template.cell(r, 1).value for r in (2, 3)) == ["E001", "E002"]

    def same(x, net_off=D("0")):
        return [
            x.employee.number,
            x.employee.full_name,
            x.gross,
            x.epf_employee,
            x.epf_employer,
            x.etf,
            x.apit,
            x.net + net_off,
        ]

    old = book(
        COMPARE_HEAD,
        [
            same(lines["E001"]),
            same(lines["E002"], D("-10.50")),
            ["E009", "Left last month", 1000, 80, 120, 30, 0, 920],
        ],
    )
    preview = takeover.compare(hr, approved.pk, old, "oct.xlsx", save=False)
    assert (preview["employees"], preview["differences"], preview["saved"]) == (3, 2, False)
    people = {p["number"]: p for p in preview["people"]}
    assert people["E001"]["differs"] is False
    net = next(f for f in people["E002"]["figures"] if f["field"] == "Net pay")
    assert net["difference"] == "10.50"
    assert people["E009"]["missing"] == "here"
    assert not ParallelCheck.objects.exists()

    saved = as_user(hr).post(
        f"{URL}compare/{approved.pk}/",
        {"file": SimpleUploadedFile("oct.xlsx", old), "save": "true"},
        format="multipart",
    )
    assert saved.status_code == 200 and saved.json()["saved"] is True
    check = ParallelCheck.objects.get()
    refused = as_user(hr).post(f"{URL}checks/{check.pk}/sign-off/", {"note": "Fine"})
    assert refused.status_code == 400 and "The Director signs off" in refused.json()["detail"]
    no_note = as_user(director).post(f"{URL}checks/{check.pk}/sign-off/", {"note": ""})
    assert "2 differences" in no_note.json()["detail"]
    signed = as_user(director).post(
        f"{URL}checks/{check.pk}/sign-off/",
        {"note": "E002: old sheet rounded the welfare; E009 left in September"},
    )
    assert signed.status_code == 200
    shown = signed.json()["checks"][0]
    assert shown["signed_off_by"] and shown["can_sign_off"] is False
    with pytest.raises(TakeoverError, match="already signed off"):
        takeover.sign_off(director, check.pk, "again")
    with pytest.raises(DatabaseError), transaction.atomic():
        ParallelCheck.objects.filter(pk=check.pk).update(differences=0)
    with pytest.raises(DatabaseError), transaction.atomic():
        ParallelCheck.objects.filter(pk=check.pk).delete()
