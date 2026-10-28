"""Number series (backlog P0-08)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError

from apps.core import numbering
from apps.core.models import AuditEvent, Division, IssuedNumber, NumberCounter, NumberSeries
from apps.core.numbering import NumberSeriesError, allocate

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

DAY = date(2026, 10, 23)


def division(code):
    return Division.objects.get(code=code)


def voucher_number(code="IM", on_date=DAY):
    with transaction.atomic():
        return allocate("voucher", division=division(code), on_date=on_date)


def series(document_type="voucher"):
    return NumberSeries.objects.get(document_type=document_type)


def set_format(number_format, reset_period="daily", document_type="voucher"):
    NumberSeries.objects.filter(document_type=document_type).update(
        format=number_format, reset_period=reset_period
    )


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


# --- The voucher format PPYYMMDDXXX -----------------------------------------------------


def test_vouchers_are_numbered_ppyymmddxxx_reset_daily():
    voucher = series()
    assert voucher.format == "{PP}{YY}{MM}{DD}{XXX}"
    assert voucher.reset_period == "daily"


def test_the_third_im_voucher_on_23_october_2026_is_im261023003():
    numbers = [voucher_number("IM") for _ in range(3)]
    assert numbers == ["IM261023001", "IM261023002", "IM261023003"]


def test_the_running_number_restarts_each_day_separately_for_each_division():
    assert voucher_number("IM") == "IM261023001"
    assert voucher_number("IM") == "IM261023002"
    assert voucher_number("WS") == "WS261023001"
    assert voucher_number("IM", date(2026, 10, 24)) == "IM261024001"
    assert voucher_number("WS") == "WS261023002"


def test_a_division_added_today_gets_its_own_numbers_at_once():
    Division.objects.create(code="TS", name="Tool Shop")
    voucher_number("IM")
    assert voucher_number("TS") == "TS261023001"


def test_the_date_is_today_in_sri_lanka_when_not_given():
    with transaction.atomic():
        number = allocate("voucher", division=division("IM"))
    assert len(number) == 11 and number.startswith("IM") and number.endswith("001")


# --- Allocated inside the saving transaction --------------------------------------------


# Without the per-test transaction, so the call really is outside any transaction.
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_numbers_are_given_only_inside_a_transaction():
    with pytest.raises(NumberSeriesError, match="saving transaction"):
        allocate("voucher", division=division("IM"), on_date=DAY)


def test_a_save_that_fails_gives_its_number_back():
    with pytest.raises(RuntimeError), transaction.atomic():
        assert allocate("voucher", division=division("IM"), on_date=DAY) == "IM261023001"
        raise RuntimeError("the voucher could not be saved")
    assert voucher_number("IM") == "IM261023001"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_50_concurrent_saves_get_50_unique_consecutive_numbers():
    im = division("IM")

    def save(_):
        try:
            with transaction.atomic():
                return allocate("voucher", division=im, on_date=DAY)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=10) as pool:
        numbers = list(pool.map(save, range(50)))

    assert sorted(numbers) == [f"IM261023{n:03d}" for n in range(1, 51)]


# --- Never reused -----------------------------------------------------------------------


def test_every_issued_number_is_kept_and_cannot_be_removed_or_changed():
    number = voucher_number("IM")
    issued = IssuedNumber.objects.get(number=number)
    with pytest.raises(DatabaseError), transaction.atomic():
        IssuedNumber.objects.filter(pk=issued.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        IssuedNumber.objects.filter(pk=issued.pk).update(number="IM261023999")


def test_a_running_number_can_never_go_back_or_be_removed():
    voucher_number("IM")
    voucher_number("IM")
    with pytest.raises(DatabaseError), transaction.atomic():
        NumberCounter.objects.update(last_number=1)
    with pytest.raises(DatabaseError), transaction.atomic():
        NumberCounter.objects.all().delete()
    assert voucher_number("IM") == "IM261023003"


def test_a_number_given_before_is_skipped_after_a_reset_change_never_reused():
    assert voucher_number("IM") == "IM261023001"
    # A new counter starts for the year, but IM261023001 was already given.
    set_format("{PP}{YY}{MM}{DD}{XXX}", "yearly")
    assert voucher_number("IM") == "IM261023002"


def test_a_division_used_for_a_number_has_its_code_fixed():
    voucher_number("IM")
    assert division("IM").in_use
    with pytest.raises(DatabaseError), transaction.atomic():
        Division.objects.filter(code="IM").update(code="PM")


# --- Running out ------------------------------------------------------------------------


def test_the_1000th_number_of_a_day_is_refused_with_a_clear_message():
    voucher_number("IM")
    NumberCounter.objects.filter(division__code="IM").update(last_number=999)
    with pytest.raises(NumberSeriesError) as refused:
        voucher_number("IM")
    message = str(refused.value)
    assert "999 numbers for division IM in 2026-10-23 have been used" in message
    assert "{XXXX}" in message
    # Nothing was used up by the refusal.
    assert NumberCounter.objects.get(division__code="IM").last_number == 999


def test_the_admin_can_widen_the_running_number():
    voucher_number("IM")
    NumberCounter.objects.filter(division__code="IM").update(last_number=999)
    set_format("{PP}{YY}{MM}{DD}{XXXX}")
    assert voucher_number("IM") == "IM2610231000"


# --- Other documents and formats --------------------------------------------------------


def test_a_format_without_a_division_shares_one_running_number():
    proforma = series("proforma")  # PI-{YYYY}-{NNNN}, reset yearly
    with transaction.atomic():
        first = allocate("proforma", division=division("IM"), on_date=DAY)
        second = allocate("proforma", division=division("WS"), on_date=DAY)
        third = allocate("proforma", on_date=date(2027, 1, 2))
    assert (first, second, third) == ("PI-2026-0001", "PI-2026-0002", "PI-2027-0001")
    assert proforma.counters.count() == 2


def test_a_document_numbered_by_division_needs_a_division():
    with pytest.raises(NumberSeriesError, match="needs a division"), transaction.atomic():
        allocate("voucher", on_date=DAY)


def test_a_deactivated_division_cannot_be_used_on_new_documents():
    Division.objects.filter(code="WS").update(is_active=False)
    with pytest.raises(NumberSeriesError, match="deactivated"):
        voucher_number("WS")


def test_an_unknown_document_type_is_refused():
    with pytest.raises(NumberSeriesError), transaction.atomic():
        allocate("nothing", on_date=DAY)


@pytest.mark.parametrize(
    "number_format, reset",
    [
        ("{PP}{YY}{MM}{DD}{XXX}", "daily"),
        ("PI-{YYYY}-{NNNN}", "yearly"),
        ("{PP}/{YY}{MM}/{NNNNN}", "monthly"),
        ("GRN{XXXXXX}", "never"),
    ],
)
def test_good_formats_are_accepted(number_format, reset):
    numbering.check(number_format, reset)


@pytest.mark.parametrize(
    "number_format, reset, why",
    [
        ("", "daily", "required"),
        ("{PP}{YY}{MM}{DD}", "daily", "one running number"),
        ("{XXX}{NN}", "never", "only one running number"),
        ("{QQ}{XXX}", "never", "Unknown token"),
        ("{PP} {XXX}", "never", "not allowed"),
        ("{YY}{YYYY}{XXX}", "yearly", "not both"),
        ("{PP}{PP}{XXX}", "never", "twice"),
        ("{PP}{YY}{MM}{XXX}", "daily", "the day"),
        ("{PP}{XXX}", "yearly", "the year"),
        ("{XXXXXXXXXX}", "never", "at most 9"),
    ],
)
def test_bad_formats_are_refused_with_the_reason(number_format, reset, why):
    with pytest.raises(NumberSeriesError, match=why):
        numbering.check(number_format, reset)


# --- Settings page API ------------------------------------------------------------------


def test_the_settings_list_shows_the_next_number_for_each_division(admin):
    with transaction.atomic():
        allocate("voucher", division=division("IM"))
    response = as_user(admin).get("/api/v1/settings/number-series/")
    assert response.status_code == 200
    [voucher] = [row for row in response.json() if row["document_type"] == "voucher"]
    nexts = {row["division"]: row["next"] for row in voucher["next_numbers"]}
    assert set(nexts) == {"HO", "IM", "WS"}
    assert nexts["IM"].endswith("002") and nexts["WS"].endswith("001")


def test_the_admin_changes_a_format_with_a_reason_and_it_is_audited(admin):
    response = as_user(admin).patch(
        f"/api/v1/settings/number-series/{series().pk}/",
        {"format": "{PP}{YY}{MM}{DD}{XXXX}", "reset_period": "daily", "reason": "busy days"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert series().format == "{PP}{YY}{MM}{DD}{XXXX}"
    [row] = AuditEvent.objects.filter(object_type="core.numberseries")
    assert row.event == "number_series_changed"
    assert row.reason == "busy days"
    assert row.changes["format"] == ["{PP}{YY}{MM}{DD}{XXX}", "{PP}{YY}{MM}{DD}{XXXX}"]


def test_a_format_change_needs_a_reason_and_a_valid_format(admin):
    url = f"/api/v1/settings/number-series/{series().pk}/"
    client = as_user(admin)
    no_reason = {"format": "{PP}{YY}{MM}{DD}{XXXX}", "reset_period": "daily"}
    assert client.patch(url, no_reason, format="json").status_code == 400
    bad = {"format": "{PP}{YY}{MM}{XXX}", "reset_period": "daily", "reason": "x"}
    response = client.patch(url, bad, format="json")
    assert response.status_code == 400
    assert "the day" in response.json()["detail"]
    assert series().format == "{PP}{YY}{MM}{DD}{XXX}"


def test_the_preview_checks_a_format_without_saving_it(admin):
    response = as_user(admin).post(
        f"/api/v1/settings/number-series/{series().pk}/preview/",
        {"format": "{PP}-{YYYY}-{NNNN}", "reset_period": "yearly"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert {r["division"] for r in response.json()["next_numbers"]} == {"HO", "IM", "WS"}
    assert all(r["next"].endswith("-0001") for r in response.json()["next_numbers"])
    assert series().format == "{PP}{YY}{MM}{DD}{XXX}"


def test_only_settings_managers_change_number_formats():
    clerk = person("clerk@sml.lk", "clerk")
    director = person("director@sml.lk", "director", all_divisions=True)
    url = f"/api/v1/settings/number-series/{series().pk}/"
    change = {"format": "{PP}{XXXXXX}", "reset_period": "never", "reason": "x"}
    assert as_user(clerk).get("/api/v1/settings/number-series/").status_code == 403
    assert as_user(director).get("/api/v1/settings/number-series/").status_code == 200
    for user in (clerk, director):
        assert as_user(user).patch(url, change, format="json").status_code == 403
    assert series().format == "{PP}{YY}{MM}{DD}{XXX}"
