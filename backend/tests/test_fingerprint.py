"""Attendance from the fingerprint machine's own file (backlog P2B-21): its "Schedule" report
(Excel 2003 XML) uploaded as it is, people matched by their Fingerprint ID, the earliest and
latest punch of each day, single punches listed, the sheet's corrections and leave kept.
The file below is made up in the machine's layout; no real attendance is used."""

from datetime import date, time

import pytest

from apps.payroll import attendance, device, employees
from apps.payroll.attendance import AttendanceError
from apps.payroll.models import AttendanceDay

from .test_access import as_user
from .test_attendance import hr, kamal, sheet, shifts  # noqa: F401 - fixtures used by name
from .test_employees import values

pytestmark = pytest.mark.django_db

DAYS = [
    # (left day, times), (right day, times); three IN/OUT pairs each.
    (("10.21", "WED", ["08:12", "17:05", "17:05", "", "", ""]),
     ("10.29", "THU", ["08:02", "", "17:20", "", "", ""])),
    (("10.22", "THU", ["08:30", "", "", "", "", ""]),  # one punch only
     ("10.30", "FRI", ["", "", "", "", "", ""])),
    (("10.23", "FRI", ["08:01", "12:30", "13:15", "17:02", "", ""]),
     ("10.31", "SAT", ["07:58", "13:30", "13:30", "", "", ""])),
]  # fmt: skip


def cell(text, index=None, merge=None):
    attrs = (f' ss:Index="{index}"' if index else "") + (
        f' ss:MergeAcross="{merge}"' if merge else ""
    )
    return f'<Cell{attrs}><Data ss:Type="String">{text}</Data></Cell>'


def block(person_id, name, days=DAYS) -> str:
    rows = [
        "<Row>"
        + cell(f"ID:{person_id}", merge=2)
        + cell(f"Name:{name}", 4, merge=2)
        + cell("Dept:Office", 7, merge=2)
        + cell("Shift:Shift1", 10, merge=2)
        + cell("Date:21/10/26~4/11/26", 13, merge=3)
        + "</Row>",
        "<Row>" + "".join(cell(h) for h in ["Date", "week"] + ["IN", "OUT"] * 3) * 2 + "</Row>",
    ]
    for (d1, w1, t1), (d2, w2, t2) in days:
        rows.append("<Row>" + "".join(cell(x) for x in [d1, w1, *t1, d2, w2, *t2]) + "</Row>")
    rows.append("<Row>" + cell("Work day: 12.2/110.00(hour);Late Times:2", merge=15) + "</Row>")
    return "".join(rows)


def machine_file(*blocks) -> bytes:
    body = (
        '﻿<?xml version="1.0" ?>\n<?mso-application progid="Excel.Sheet"?>\n'
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Schedule"><Table>'
        + "".join(blocks)
        + "</Table></Worksheet></Workbook>"
    )
    # The machine writes some bytes that are not UTF-8 in its totals lines.
    return body.encode("utf-8").replace(b"Late Times", b"Sick leave\xa3\xba Late Times")


def test_the_machine_file_is_read():
    content = machine_file(block("220", "Test One"), block("230", "Nobody", days=[]))
    assert device.is_device_file(content)
    first, second = device.read(content)
    assert (first["id"], first["name"], second["days"]) == ("220", "Test One", {})
    days = first["days"]
    assert days[date(2026, 10, 21)] == [time(8, 12), time(17, 5)]
    assert days[date(2026, 10, 29)] == [time(8, 2), time(17, 20)]
    assert days[date(2026, 10, 22)] == [time(8, 30)]
    assert days[date(2026, 10, 23)][0] == time(8, 1) and days[date(2026, 10, 23)][-1] == time(17, 2)
    assert date(2026, 10, 30) not in days
    with pytest.raises(AttendanceError, match="could not be read"):
        device.read(b'<Workbook xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><oops')


def test_the_fingerprint_id_is_set_on_the_employee(hr, kamal):  # noqa: F811
    employees.update(hr, kamal, {"device_id": "220"})
    other = employees.create(hr, values(number="E002", nic="198812345678", epf_no="9002"))
    with pytest.raises(employees.EmployeeError, match="already E001"):
        employees.update(hr, other, {"device_id": "220"})
    with pytest.raises(employees.EmployeeError, match="the number the machine shows"):
        employees.update(hr, other, {"device_id": "22 0!"})
    employees.update(hr, other, {"device_id": ""})  # blank is allowed for many
    assert as_user(hr).get(f"/api/v1/employees/{kamal.pk}/").json()["device_id"] == "220"


def test_the_machine_file_goes_through_the_attendance_upload(hr, kamal, shifts):  # noqa: F811
    content = machine_file(block("220", "Test One"), block("999", "Not set up"))
    employees.update(hr, kamal, {"device_id": "220"})
    refused = attendance.import_sheet(hr, content, "01Schedule.XLS", dry_run=True)
    assert refused["source"] == "device" and refused["saved"] is False
    assert "ID 999 (Not set up): no employee has this Fingerprint ID" in refused["errors"][0]

    # HR's correction of 23 October from the sheet stays as it is.
    attendance.import_sheet(
        hr,
        sheet(
            [
                {
                    "number": "E001",
                    "date": date(2026, 10, 23),
                    "time_in": "08:00",
                    "time_out": "17:00",
                    "shift": "DX",
                }
            ]
        ),
        "fix.xlsx",
        dry_run=False,
    )
    content = machine_file(block("220", "Test One"))
    preview = attendance.import_sheet(hr, content, "01Schedule.XLS", dry_run=True)
    assert (preview["errors"], preview["rows"], preview["saved"]) == ([], 3, False)
    assert any("2026-10-22: only one punch (08:30)" in n for n in preview["notes"])
    assert any("2026-10-23: kept as entered" in n for n in preview["notes"])

    from django.core.files.uploadedfile import SimpleUploadedFile

    saved = as_user(hr).post(
        "/api/v1/attendance/import/",
        {"file": SimpleUploadedFile("01Schedule.XLS", content), "dry_run": "false"},
        format="multipart",
    )
    assert saved.status_code == 200 and saved.json()["saved"] is True
    day = AttendanceDay.objects.get(employee=kamal, date=date(2026, 10, 21))
    assert (day.time_in, day.time_out, day.source.kind) == (time(8, 12), time(17, 5), "device")
    assert day.shift is not None and day.shift.start_time == time(8) and day.late_minutes == 12
    assert AttendanceDay.objects.get(date=date(2026, 10, 23)).source.kind == "sheet"
    assert not AttendanceDay.objects.filter(date=date(2026, 10, 22)).exists()
    # Uploading the same file again replaces the machine's days, never duplicates them.
    attendance.import_sheet(hr, content, "01Schedule.XLS", dry_run=False)
    assert AttendanceDay.objects.filter(employee=kamal).count() == 4
