"""Company profile and divisions (backlog P0-07)."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError, IntegrityError

from apps.core import organisation
from apps.core.models import AuditEvent, Company, Division

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", divisions=["IM"])


@pytest.fixture
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


def division(code):
    return Division.objects.get(code=code)


def picker(user, **params):
    response = as_user(user).get("/api/v1/divisions/", params)
    assert response.status_code == 200
    return [d["code"] for d in response.json()]


def create(user, **data):
    return as_user(user).post("/api/v1/settings/divisions/", data, format="json")


def change(user, div, **data):
    return as_user(user).patch(f"/api/v1/settings/divisions/{div.pk}/", data, format="json")


def remove(user, div, reason="set up by mistake"):
    return as_user(user).delete(
        f"/api/v1/settings/divisions/{div.pk}/", {"reason": reason}, format="json"
    )


# --- Company profile --------------------------------------------------------------------


def test_the_company_profile_exists_with_lkr_and_an_april_financial_year():
    company = Company.get()
    assert company.name == "SML Engineers"
    assert company.base_currency == "LKR"
    assert company.financial_year_start_month == 4


def test_everyone_signed_in_can_read_the_company_profile(clerk):
    response = as_user(clerk).get("/api/v1/company/")
    assert response.status_code == 200
    assert response.json()["name"] == "SML Engineers"


def test_the_admin_updates_the_company_profile_and_it_is_audited(admin):
    response = as_user(admin).put(
        "/api/v1/company/",
        {
            "name": "SML Engineers (Pvt) Ltd",
            "registration_no": "PV 12345",
            "vat_no": "123456789-7000",
            "address": "Colombo",
            "financial_year_start_month": 1,
            "reason": "registration certificate",
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    company = Company.get()
    assert company.registration_no == "PV 12345"
    assert company.financial_year_start_month == 1
    [row] = AuditEvent.objects.filter(object_type="core.company")
    assert row.event == "company_updated"
    assert row.reason == "registration certificate"
    assert row.changes["vat_no"] == ["", "123456789-7000"]


def test_only_settings_managers_can_change_the_company_profile(clerk, director):
    for user in (clerk, director):
        response = as_user(user).put("/api/v1/company/", {"name": "X"}, format="json")
        assert response.status_code == 403
    assert Company.get().name == "SML Engineers"


def test_the_company_name_is_required(admin):
    response = as_user(admin).put("/api/v1/company/", {"name": "  "}, format="json")
    assert response.status_code == 400


def test_an_invalid_financial_year_month_is_refused(admin):
    response = as_user(admin).put(
        "/api/v1/company/", {"financial_year_start_month": 13}, format="json"
    )
    assert response.status_code == 400


def test_the_base_currency_cannot_be_changed(admin):
    response = as_user(admin).put("/api/v1/company/", {"base_currency": "USD"}, format="json")
    assert response.status_code == 400
    assert Company.get().base_currency == "LKR"


def test_the_database_refuses_a_base_currency_change_or_deleting_the_company():
    with pytest.raises(DatabaseError), transaction.atomic():
        Company.objects.filter(pk=1).update(base_currency="USD")
    with pytest.raises(DatabaseError), transaction.atomic():
        Company.objects.filter(pk=1).delete()
    with pytest.raises(IntegrityError), transaction.atomic():
        Company.objects.create(id=2, name="Second company")


# --- Company logo -----------------------------------------------------------------------


def upload(user, content, name="logo.png"):
    return as_user(user).put(
        "/api/v1/company/logo/",
        {"logo": SimpleUploadedFile(name, content)},
        format="multipart",
    )


def test_the_admin_uploads_a_logo_and_everyone_can_fetch_it(admin, clerk, memory_storage):
    response = upload(admin, PNG)
    assert response.status_code == 200, response.json()
    assert response.json()["has_logo"] is True

    fetched = as_user(clerk).get("/api/v1/company/logo/")
    assert fetched.status_code == 200
    assert fetched["Content-Type"] == "image/png"
    assert b"".join(fetched.streaming_content) == PNG


def test_a_jpeg_logo_is_accepted(admin, memory_storage):
    assert upload(admin, JPEG, "logo.jpeg").status_code == 200
    assert Company.get().logo.name.endswith(".jpg")


def test_a_file_that_is_not_a_png_or_jpeg_is_refused_whatever_its_name(admin, memory_storage):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    response = upload(admin, svg, "logo.png")
    assert response.status_code == 400
    assert not Company.get().logo


def test_a_logo_over_1_mb_is_refused(admin, memory_storage):
    response = upload(admin, PNG + b"\x00" * (1024 * 1024))
    assert response.status_code == 400


def test_only_settings_managers_can_change_the_logo(clerk, memory_storage):
    assert upload(clerk, PNG).status_code == 403


def test_the_logo_can_be_removed(admin, memory_storage):
    upload(admin, PNG)
    response = as_user(admin).delete("/api/v1/company/logo/")
    assert response.status_code == 200
    assert response.json()["has_logo"] is False
    assert as_user(admin).get("/api/v1/company/logo/").status_code == 404


# --- Divisions: the starting set --------------------------------------------------------


def test_the_starting_divisions_are_ws_im_and_ho():
    rows = {d.code: (d.name, d.division_type) for d in Division.objects.all()}
    assert rows == {
        "WS": ("Workshop", "production"),
        "IM": ("Plastic Injection Moulding", "production"),
        "HO": ("Head Office", "shared"),
    }


# --- Adding a division on a running system ----------------------------------------------


def test_a_division_added_through_the_api_is_usable_at_once(admin, clerk):
    response = create(admin, code="ts", name="Tool Shop", division_type="production")
    assert response.status_code == 201, response.json()
    assert response.json()["code"] == "TS"  # stored upper-case

    # Straight away, with no restart: in the picker for everyone who sees all divisions...
    assert "TS" in picker(admin)
    # ...and it can be given to a user, who then sees it in their own pickers.
    response = as_user(admin).put(
        f"/api/v1/users/{clerk.pk}/scope/",
        {"all_divisions": False, "divisions": ["IM", "TS"]},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert picker(clerk) == ["IM", "TS"]


def test_a_new_division_leaves_the_existing_divisions_unchanged(admin):
    before = list(Division.objects.values_list("code", "name", "division_type", "is_active"))
    create(admin, code="TS", name="Tool Shop")
    after = list(
        Division.objects.exclude(code="TS").values_list(
            "code", "name", "division_type", "is_active"
        )
    )
    assert after == before


def test_users_without_that_division_do_not_see_it(admin, clerk):
    create(admin, code="TS", name="Tool Shop")
    assert picker(clerk) == ["IM"]
    assert as_user(clerk).get("/api/v1/divisions/TS/").status_code == 404


def test_adding_a_division_is_audited_with_the_reason(admin):
    create(admin, code="TS", name="Tool Shop", reason="new tool room")
    [row] = AuditEvent.objects.filter(object_type="core.division", action="create")
    assert row.event == "division_created"
    assert row.reason == "new tool room"
    assert row.actor_email == "admin@sml.lk"


@pytest.mark.parametrize("code", ["T", "TSX", "T-", "  ", "é1"])
def test_a_division_code_must_be_two_letters_or_digits(admin, code):
    response = create(admin, code=code, name="Tool Shop")
    assert response.status_code == 400
    assert not Division.objects.filter(name="Tool Shop").exists()


def test_the_database_refuses_a_badly_formed_code():
    with pytest.raises(IntegrityError), transaction.atomic():
        Division.objects.create(code="ts", name="Tool Shop")


def test_codes_and_names_must_be_unique(admin):
    assert create(admin, code="IM", name="Another").status_code == 400
    assert create(admin, code="XX", name="workshop").status_code == 400


def test_the_type_must_be_production_or_shared(admin):
    assert create(admin, code="TS", name="Tool Shop", division_type="other").status_code == 400


def test_only_settings_managers_can_add_or_change_divisions(clerk, director):
    for user in (clerk, director):
        assert create(user, code="TS", name="Tool Shop").status_code == 403
        assert change(user, division("IM"), name="X").status_code == 403
        assert remove(user, division("HO")).status_code == 403
    assert not Division.objects.filter(code="TS").exists()


def test_the_control_panel_list_needs_settings_access(clerk, director):
    assert as_user(clerk).get("/api/v1/settings/divisions/").status_code == 403
    response = as_user(director).get("/api/v1/settings/divisions/")
    assert response.status_code == 200
    assert {d["code"] for d in response.json()} == {"WS", "IM", "HO"}


# --- Renaming and the code lock ---------------------------------------------------------


def test_a_division_can_be_renamed_at_any_time(admin):
    organisation.mark_division_used(division("IM"))
    response = change(admin, division("IM"), name="Injection Moulding")
    assert response.status_code == 200, response.json()
    assert division("IM").name == "Injection Moulding"


def test_the_code_can_be_corrected_while_the_division_is_unused(admin):
    create(admin, code="TX", name="Tool Shop")
    response = change(admin, division("TX"), code="TS")
    assert response.status_code == 200, response.json()
    assert Division.objects.filter(code="TS").exists()


def test_the_code_cannot_change_once_the_division_is_used_on_a_document(admin):
    organisation.mark_division_used(division("IM"))
    response = change(admin, division("IM"), code="PM")
    assert response.status_code == 400
    assert "cannot change" in response.json()["detail"]
    assert division("IM").code == "IM"


def test_the_database_refuses_a_code_change_on_a_used_division():
    organisation.mark_division_used(division("IM"))
    with pytest.raises(DatabaseError), transaction.atomic():
        Division.objects.filter(code="IM").update(code="PM")
    with pytest.raises(DatabaseError), transaction.atomic():
        Division.objects.filter(code="IM").update(first_used_at=None)


def test_marking_a_division_used_keeps_the_first_date():
    im = division("IM")
    organisation.mark_division_used(im)
    first = division("IM").first_used_at
    organisation.mark_division_used(division("IM"))
    assert division("IM").first_used_at == first
    assert AuditEvent.objects.filter(event="division_first_used").count() == 1


def test_the_control_panel_shows_whether_a_code_is_locked(admin):
    organisation.mark_division_used(division("IM"))
    rows = {d["code"]: d for d in as_user(admin).get("/api/v1/settings/divisions/").json()}
    assert rows["IM"]["in_use"] is True
    assert rows["WS"]["in_use"] is False


# --- Deactivating and deleting ----------------------------------------------------------


def test_deactivating_needs_a_reason(admin):
    assert change(admin, division("WS"), is_active=False).status_code == 400
    assert division("WS").is_active


def test_a_deactivated_division_leaves_the_pickers_but_stays_in_filters(admin):
    response = change(admin, division("WS"), is_active=False, reason="workshop closed")
    assert response.status_code == 200, response.json()
    assert "WS" not in picker(admin)
    assert "WS" in picker(admin, include_inactive="1")
    [row] = AuditEvent.objects.filter(event="division_deactivated")
    assert row.reason == "workshop closed"


def test_a_deactivated_division_can_be_reactivated(admin):
    change(admin, division("WS"), is_active=False, reason="closed")
    assert change(admin, division("WS"), is_active=True).status_code == 200
    assert "WS" in picker(admin)
    assert AuditEvent.objects.filter(event="division_reactivated").exists()


def test_at_least_one_division_stays_active(admin):
    change(admin, division("WS"), is_active=False, reason="x")
    change(admin, division("HO"), is_active=False, reason="x")
    response = change(admin, division("IM"), is_active=False, reason="x")
    assert response.status_code == 400
    assert division("IM").is_active


def test_an_unused_division_set_up_by_mistake_can_be_deleted(admin):
    create(admin, code="TS", name="Tool Shop")
    response = remove(admin, division("TS"), reason="typo, meant WS")
    assert response.status_code == 204
    assert not Division.objects.filter(code="TS").exists()
    [row] = AuditEvent.objects.filter(object_type="core.division", action="delete")
    assert row.event == "division_deleted"
    assert row.reason == "typo, meant WS"


def test_deleting_needs_a_reason(admin):
    create(admin, code="TS", name="Tool Shop")
    assert remove(admin, division("TS"), reason="").status_code == 400


def test_a_division_used_on_documents_cannot_be_deleted_only_deactivated(admin):
    organisation.mark_division_used(division("IM"))
    response = remove(admin, division("IM"))
    assert response.status_code == 400
    assert "only deactivated" in response.json()["detail"]
    assert Division.objects.filter(code="IM").exists()


def test_the_database_refuses_to_delete_a_used_division():
    organisation.mark_division_used(division("IM"))
    with pytest.raises(DatabaseError), transaction.atomic():
        Division.objects.filter(code="IM").delete()


def test_a_division_with_users_assigned_cannot_be_deleted(admin, clerk):
    response = remove(admin, division("IM"))
    assert response.status_code == 400
    assert "user" in response.json()["detail"]
    assert Division.objects.filter(code="IM").exists()
