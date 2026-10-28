"""Divisions, sections and machines (backlog P0-09, spec 3A.1)."""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from apps.core.models import AuditEvent, Division
from apps.core.organisation import is_in_use as division_in_use
from apps.masters import excel, services
from apps.masters.models import Machine, MachineRate, Section

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


def section(code):
    return Section.objects.get(code=code)


def machine(code="M-MIL-01", section_code="M-MIL", **data):
    return services.create_machine(
        code=code, section=section(section_code), name=data.pop("name", "Milling 1"), **data
    )


def today():
    return timezone.localdate()


# --- Starting data ----------------------------------------------------------------------


def test_the_workshop_starts_with_the_18_sections_of_the_spec():
    workshop = Section.objects.filter(division__code="WS")
    assert workshop.count() == 18
    assert workshop.filter(category="manual").count() == 9
    assert workshop.filter(category="cnc").count() == 9
    assert set(workshop.values_list("section_type", flat=True)) == {"machining"}
    assert section("M-MIL").name == "Manual Milling"
    assert section("C-WED").name == "Wire EDM"


def test_moulding_has_a_section_for_its_machines_and_no_machine_is_preloaded():
    assert section("IM-MLD").division.code == "IM"
    assert section("IM-MLD").section_type == "moulding"
    assert Machine.objects.count() == 0


def test_sections_do_not_fix_a_division_code():
    assert not division_in_use(Division.objects.get(code="WS"))


# --- Sections ---------------------------------------------------------------------------


def add_section(user, **data):
    return as_user(user).post("/api/v1/settings/sections/", data, format="json")


def change_section(user, section_code, **data):
    pk = section(section_code).pk
    return as_user(user).patch(f"/api/v1/settings/sections/{pk}/", data, format="json")


def test_the_admin_adds_a_section_with_supervisors(admin):
    supervisor = person("sup@sml.lk", "production_supervisor", divisions=["WS"])
    response = add_section(
        admin,
        code="m-tap",
        name="Manual Tapping",
        division="WS",
        section_type="machining",
        category="manual",
        supervisors=[supervisor.pk],
        reason="new bench",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["code"] == "M-TAP"
    assert response.json()["supervisors"] == [{"id": supervisor.pk, "name": "Sup"}]
    [row] = AuditEvent.objects.filter(object_type="masters.section", action="create")
    assert row.event == "section_created" and row.reason == "new bench"


@pytest.mark.parametrize(
    "data, why",
    [
        ({"code": "M MIL"}, "code"),
        ({"code": "M-MIL"}, "already used"),
        ({"category": ""}, "Manual or CNC"),
        ({"section_type": "support", "category": "cnc"}, "Only machining"),
        ({"division": "ZZ"}, "Unknown division"),
        ({"name": " "}, "name is required"),
    ],
)
def test_a_section_must_be_valid(admin, data, why):
    base = {
        "code": "M-TAP",
        "name": "Manual Tapping",
        "division": "WS",
        "section_type": "machining",
        "category": "manual",
    }
    response = add_section(admin, **(base | data))
    assert response.status_code == 400
    assert why in response.json()["detail"]


def test_a_section_can_be_renamed_and_its_code_corrected_while_unused(admin):
    assert change_section(admin, "M-MIL", name="Manual Milling Bay").status_code == 200
    assert change_section(admin, "M-MIL", code="M-MILL").status_code == 200
    assert section("M-MILL").name == "Manual Milling Bay"


def test_a_used_section_keeps_its_code_and_cannot_be_deleted(admin):
    services.mark_used(section("M-MIL"))
    response = change_section(admin, "M-MIL", code="M-MILL")
    assert response.status_code == 400
    assert "cannot change" in response.json()["detail"]
    response = as_user(admin).delete(
        f"/api/v1/settings/sections/{section('M-MIL').pk}/", {"reason": "x"}, format="json"
    )
    assert response.status_code == 400
    assert "only made inactive" in response.json()["detail"]


def test_the_database_guards_used_sections_and_machines():
    services.mark_used(section("M-MIL"))
    with pytest.raises(DatabaseError), transaction.atomic():
        Section.objects.filter(code="M-MIL").update(code="M-MILL")
    with pytest.raises(DatabaseError), transaction.atomic():
        Section.objects.filter(code="M-MIL").delete()
    services.mark_used(machine())
    with pytest.raises(DatabaseError), transaction.atomic():
        Machine.objects.filter(code="M-MIL-01").update(code="M-MIL-99")
    with pytest.raises(DatabaseError), transaction.atomic():
        Machine.objects.filter(code="M-MIL-01").update(first_used_at=None)


def test_making_a_section_inactive_needs_a_reason_and_hides_it_from_entry_pages(admin):
    assert change_section(admin, "M-SHP", is_active=False).status_code == 400
    response = change_section(admin, "M-SHP", is_active=False, reason="no shaping work")
    assert response.status_code == 200
    codes = [s["code"] for s in as_user(admin).get("/api/v1/sections/").json()]
    assert "M-SHP" not in codes
    every = as_user(admin).get("/api/v1/sections/", {"include_inactive": "1"}).json()
    assert "M-SHP" in [s["code"] for s in every]


def test_an_unused_empty_section_can_be_deleted_but_not_one_with_machines(admin):
    url = f"/api/v1/settings/sections/{section('M-SHP').pk}/"
    machine("M-SHP-01", "M-SHP")
    response = as_user(admin).delete(url, {"reason": "x"}, format="json")
    assert response.status_code == 400
    assert "1 machines" in response.json()["detail"]
    Machine.objects.filter(code="M-SHP-01").delete()
    assert as_user(admin).delete(url, {"reason": "not needed"}, format="json").status_code == 204


def test_a_section_with_machines_cannot_move_to_another_division(admin):
    machine()
    response = change_section(admin, "M-MIL", division="IM")
    assert response.status_code == 400
    assert section("M-MIL").division.code == "WS"


# --- Machines ---------------------------------------------------------------------------


def add_machine(user, **data):
    return as_user(user).post("/api/v1/settings/machines/", data, format="json")


def test_the_admin_adds_a_moulding_machine_with_its_size(admin):
    response = add_machine(
        admin,
        code="IMM-01",
        name="Haitian 250",
        section="IM-MLD",
        make="Haitian",
        model="MA2500",
        year=2019,
        clamping_force_t="250",
        max_shot_weight_g="455.5",
        tie_bar_h_mm="570",
        tie_bar_v_mm="570",
    )
    assert response.status_code == 201, response.json()
    saved = Machine.objects.get(code="IMM-01")
    assert saved.clamping_force_t == Decimal("250.0")
    assert saved.max_shot_weight_g == Decimal("455.5")
    assert response.json()["division"] == "IM"


@pytest.mark.parametrize(
    "data, why",
    [
        ({"clamping_force_t": "-5"}, "negative"),
        ({"clamping_force_t": "1.25"}, "one decimal"),
        ({"clamping_force_t": "lots"}, "number"),
        ({"year": 1800}, "valid year"),
        ({"status": "broken"}, "status"),
        ({"section": "NOPE"}, "Unknown section"),
    ],
)
def test_a_machine_must_be_valid(admin, data, why):
    base = {"code": "IMM-01", "name": "Haitian 250", "section": "IM-MLD"}
    response = add_machine(admin, **(base | data))
    assert response.status_code == 400
    assert why in response.json()["detail"]


def test_a_machine_can_move_to_another_section(admin):
    m = machine()
    response = as_user(admin).patch(
        f"/api/v1/settings/machines/{m.pk}/", {"section": "C-MIL"}, format="json"
    )
    assert response.status_code == 200
    assert Machine.objects.get(pk=m.pk).section.code == "C-MIL"
    [row] = AuditEvent.objects.filter(object_type="masters.machine", event="machine_moved")
    assert row.changes["section"] == ["M-MIL Manual Milling", "C-MIL CNC Milling"]


def test_retiring_needs_a_reason_and_hides_the_machine_from_entry_pages(admin):
    m = machine()
    url = f"/api/v1/settings/machines/{m.pk}/"
    assert as_user(admin).patch(url, {"status": "retired"}, format="json").status_code == 400
    response = as_user(admin).patch(url, {"status": "retired", "reason": "sold"}, format="json")
    assert response.status_code == 200
    assert as_user(admin).get("/api/v1/machines/").json() == []
    retired = as_user(admin).get("/api/v1/machines/", {"include_retired": "1"}).json()
    assert [r["code"] for r in retired] == ["M-MIL-01"]


def test_a_used_machine_keeps_its_code_and_cannot_be_deleted(admin):
    m = machine()
    services.mark_used(m)
    url = f"/api/v1/settings/machines/{m.pk}/"
    assert as_user(admin).patch(url, {"code": "M-MIL-09"}, format="json").status_code == 400
    response = as_user(admin).delete(url, {"reason": "x"}, format="json")
    assert response.status_code == 400
    assert "only retired" in response.json()["detail"]


def test_a_machine_entered_by_mistake_can_be_deleted(admin):
    m = machine()
    response = as_user(admin).delete(
        f"/api/v1/settings/machines/{m.pk}/", {"reason": "duplicate"}, format="json"
    )
    assert response.status_code == 204
    assert not Machine.objects.filter(pk=m.pk).exists()


def test_a_machine_photo_must_be_an_image(admin, memory_storage):
    m = machine()
    url = f"/api/v1/settings/machines/{m.pk}/photo/"
    bad = as_user(admin).put(
        url, {"photo": SimpleUploadedFile("p.png", b"<svg/>")}, format="multipart"
    )
    assert bad.status_code == 400
    good = as_user(admin).put(url, {"photo": SimpleUploadedFile("p.png", PNG)}, format="multipart")
    assert good.status_code == 200
    assert good.json()["has_photo"] is True
    assert b"".join(as_user(admin).get(url).streaming_content) == PNG


# --- Hourly machine rates (effective-dated) ---------------------------------------------


def test_a_new_rate_applies_from_its_date_and_earlier_work_keeps_the_old_rate(admin):
    m = machine()
    services.add_rate(m, effective_from=today(), rate="2500.00")
    services.add_rate(m, effective_from=today() + timedelta(days=10), rate="2750.50")
    assert services.rate_on(m, today()) == Decimal("2500.00")
    assert services.rate_on(m, today() + timedelta(days=9)) == Decimal("2500.00")
    assert services.rate_on(m, today() + timedelta(days=10)) == Decimal("2750.50")
    assert services.rate_on(m, today() - timedelta(days=1)) is None


def test_a_rate_is_added_through_the_api_with_an_exact_amount(admin):
    m = machine()
    response = as_user(admin).post(
        f"/api/v1/settings/machines/{m.pk}/rates/",
        {"effective_from": today().isoformat(), "rate": "1234567.89", "reason": "costing"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["rate"] == "1234567.89"
    assert as_user(admin).get(f"/api/v1/settings/machines/{m.pk}/").json()["current_rate"] == (
        "1234567.89"
    )


@pytest.mark.parametrize(
    "rate, days, why",
    [
        ("2500.00", -1, "past"),
        ("-1", 0, "negative"),
        ("10.005", 0, "two decimal"),
        ("abc", 0, "amount"),
    ],
)
def test_a_rate_must_be_valid(rate, days, why):
    with pytest.raises(services.MastersError, match=why):
        services.add_rate(machine(), effective_from=today() + timedelta(days=days), rate=rate)


def test_a_rate_in_force_cannot_be_changed_or_removed():
    m = machine()
    rate = services.add_rate(m, effective_from=today(), rate="2500")
    with pytest.raises(services.MastersError, match="already in force"):
        services.remove_rate(rate, reason="x")
    with pytest.raises(DatabaseError), transaction.atomic():
        MachineRate.objects.filter(pk=rate.pk).update(rate=Decimal("1"))
    with pytest.raises(DatabaseError), transaction.atomic():
        MachineRate.objects.filter(pk=rate.pk).delete()


def test_a_future_rate_entered_by_mistake_can_be_removed(admin):
    m = machine()
    rate = services.add_rate(m, effective_from=today() + timedelta(days=5), rate="3000")
    response = as_user(admin).delete(
        f"/api/v1/settings/machines/{m.pk}/rates/{rate.pk}/", {"reason": "typo"}, format="json"
    )
    assert response.status_code == 204
    assert not MachineRate.objects.filter(pk=rate.pk).exists()


def test_a_machine_with_rate_history_is_retired_not_deleted():
    m = machine()
    services.add_rate(m, effective_from=today(), rate="2500")
    with pytest.raises(services.MastersError, match="retire it"):
        services.delete_machine(m, reason="x")


# --- Section scope ----------------------------------------------------------------------


def test_a_supervisor_limited_to_manual_milling_sees_only_manual_milling(admin):
    machine()
    machine("C-MIL-01", "C-MIL", name="CNC Mill 1")
    supervisor = person("sup@sml.lk", "production_supervisor", divisions=["WS"])
    response = as_user(admin).put(
        f"/api/v1/users/{supervisor.pk}/sections/",
        {"all_sections": False, "sections": ["M-MIL"]},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json() == {"all_sections": False, "sections": ["M-MIL"]}

    supervisor.refresh_from_db()  # as signed in after the change
    sees = as_user(supervisor)
    assert [s["code"] for s in sees.get("/api/v1/sections/").json()] == ["M-MIL"]
    assert [m["code"] for m in sees.get("/api/v1/machines/").json()] == ["M-MIL-01"]
    assert sees.get("/api/v1/machines/", {"section": "C-MIL"}).json() == []


def test_a_supervisor_sees_the_sections_they_supervise():
    supervisor = person("sup@sml.lk", "production_supervisor", divisions=["WS"])
    supervisor.all_sections = False
    supervisor.save()
    section("C-LAT").supervisors.add(supervisor)
    codes = [s.code for s in services.section_scope(supervisor)]
    assert codes == ["C-LAT"]


def test_users_with_all_sections_see_every_section_of_their_divisions_only():
    planner = person("plan@sml.lk", "production_planner", divisions=["IM"])
    assert [s.code for s in services.section_scope(planner)] == ["IM-MLD"]


def test_section_scope_changes_are_audited_and_not_for_ones_own_account(admin):
    supervisor = person("sup@sml.lk", "production_supervisor", divisions=["WS"])
    as_user(admin).put(
        f"/api/v1/users/{supervisor.pk}/sections/",
        {"all_sections": False, "sections": ["M-MIL", "M-LAT"]},
        format="json",
    )
    row = AuditEvent.objects.filter(event="sections_changed", changes__has_key="sections").get()
    assert row.changes["sections"] == [[], ["M-LAT", "M-MIL"]]
    own = as_user(admin).put(
        f"/api/v1/users/{admin.pk}/sections/", {"all_sections": True}, format="json"
    )
    assert own.status_code == 403


# --- Who may change the factory structure -----------------------------------------------


def test_only_settings_managers_change_sections_and_machines():
    clerk = person("clerk@sml.lk", "clerk", divisions=["WS"])
    director = person("director@sml.lk", "director", all_divisions=True)
    data = {"code": "M-TAP", "name": "T", "division": "WS", "section_type": "support"}
    assert as_user(clerk).get("/api/v1/settings/sections/").status_code == 403
    assert as_user(director).get("/api/v1/settings/sections/").status_code == 200
    for user in (clerk, director):
        assert add_section(user, **data).status_code == 403
        assert add_machine(user, code="X-1", name="X", section="M-MIL").status_code == 403
        assert as_user(user).get("/api/v1/settings/factory/export/").status_code in (200, 403)
    assert as_user(clerk).get("/api/v1/settings/factory/export/").status_code == 403


# --- Excel export and import ------------------------------------------------------------


def workbook_bytes(sections=(), machines=()):
    book = Workbook()
    book.remove(book.active)
    sheet = book.create_sheet("Sections")
    sheet.append(excel.SECTION_COLUMNS)
    for row in sections:
        sheet.append(row)
    sheet = book.create_sheet("Machines")
    sheet.append(excel.MACHINE_COLUMNS)
    for row in machines:
        sheet.append(row)
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def machine_row(code="IMM-01", section_code="IM-MLD", rate=None, rate_from=None, **extra):
    row = dict.fromkeys(excel.MACHINE_COLUMNS)
    row.update({"Code": code, "Name": "Haitian 250", "Section": section_code, "Status": "Active"})
    row.update({"Hourly rate (LKR)": rate, "Rate from": rate_from, **extra})
    return [row[c] for c in excel.MACHINE_COLUMNS]


def upload(user, content, reason="initial machine list", dry_run=False):
    return as_user(user).post(
        "/api/v1/settings/factory/import/",
        {
            "file": SimpleUploadedFile("machines.xlsx", content),
            "reason": reason,
            "dry_run": "1" if dry_run else "",
        },
        format="multipart",
    )


def test_the_export_lists_every_section_and_machine(admin):
    m = machine()
    services.add_rate(m, effective_from=today(), rate="2500.50")
    response = as_user(admin).get("/api/v1/settings/factory/export/")
    assert response.status_code == 200
    assert "sections-and-machines" in response["Content-Disposition"]
    book = load_workbook(io.BytesIO(response.content))
    sections = list(book["Sections"].iter_rows(values_only=True))
    assert sections[0] == tuple(excel.SECTION_COLUMNS)
    assert len(sections) == 1 + Section.objects.count()
    [header, row] = list(book["Machines"].iter_rows(values_only=True))
    assert row[0] == "M-MIL-01" and row[2] == "M-MIL"
    assert Decimal(repr(row[16])) == Decimal("2500.5")


def test_importing_the_export_again_changes_nothing(admin):
    m = machine(clamping_force_t="250.5")
    services.add_rate(m, effective_from=today(), rate="2500.50")
    exported = as_user(admin).get("/api/v1/settings/factory/export/").content
    before = AuditEvent.objects.count()
    response = upload(admin, exported)
    assert response.status_code == 200, response.json()
    assert response.json()["machines_updated"] == 1
    assert MachineRate.objects.count() == 1
    assert Machine.objects.get(code="M-MIL-01").clamping_force_t == Decimal("250.5")
    # Nothing actually changed, so nothing new in the audit log.
    assert AuditEvent.objects.count() == before


def test_an_import_adds_machines_with_their_rate(admin):
    content = workbook_bytes(
        machines=[
            machine_row("IMM-01", rate=3200.5, **{"Clamping force (t)": 250}),
            machine_row("IMM-02", rate=3500),
        ]
    )
    response = upload(admin, content)
    assert response.status_code == 200, response.json()
    assert response.json()["machines_created"] == 2
    first = Machine.objects.get(code="IMM-01")
    assert first.clamping_force_t == Decimal("250.0")
    assert services.rate_on(first, today()) == Decimal("3200.50")


def test_a_trial_import_checks_without_saving(admin):
    response = upload(admin, workbook_bytes(machines=[machine_row()]), dry_run=True)
    assert response.status_code == 200, response.json()
    assert response.json() == {
        "dry_run": True,
        "sections_created": 0,
        "sections_updated": 0,
        "machines_created": 1,
        "machines_updated": 0,
    }
    assert not Machine.objects.exists()


def test_an_import_with_any_bad_row_saves_nothing_and_lists_every_problem(admin):
    content = workbook_bytes(
        sections=[["M-TAP", "Manual Tapping", "WS", "Machining", "Manual", "", "Yes"]],
        machines=[
            machine_row("IMM-01"),
            machine_row("IMM-02", section_code="NOPE"),
            machine_row("IMM-03", **{"Status": "Broken"}),
        ],
    )
    response = upload(admin, content)
    assert response.status_code == 400
    errors = response.json()["errors"]
    assert errors == [
        "Machines row 3: Unknown section 'NOPE'.",
        "Machines row 4: Status must be one of: Active, Under maintenance, Retired.",
    ]
    assert not Section.objects.filter(code="M-TAP").exists()
    assert not Machine.objects.exists()


def test_an_import_needs_a_reason_and_an_excel_file(admin):
    assert upload(admin, workbook_bytes(machines=[machine_row()]), reason="").status_code == 400
    response = upload(admin, b"not a workbook")
    assert response.status_code == 400
    assert response.json()["errors"] == ["The file is not an Excel workbook (.xlsx)."]
