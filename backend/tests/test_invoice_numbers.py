"""Tax invoice and quotation numbers (backlog P0-08b; Gazette 2481/22 YYMMM_QQQQ_XXXXX)."""

from datetime import date

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.core import numbering
from apps.core.models import Division, NumberCounter, NumberSeries
from apps.core.numbering import NumberSeriesError, allocate

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

SEP = date(2026, 9, 22)


@pytest.fixture(autouse=True)
def codes():
    Division.objects.filter(code="WS").update(tax_invoice_code="W1")
    Division.objects.filter(code="IM").update(tax_invoice_code="P1")


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


def division(code):
    return Division.objects.get(code=code)


def invoice(code="WS", on_date=SEP):
    with transaction.atomic():
        return allocate("tax_invoice", division=division(code), on_date=on_date)


def quotation(on_date):
    with transaction.atomic():
        return allocate("quotation", on_date=on_date)


def change_division(user, code, **data):
    return as_user(user).patch(
        f"/api/v1/settings/divisions/{division(code).pk}/", data, format="json"
    )


# --- The tax invoice number YYMMM_XX_PP -------------------------------------------------


def test_tax_invoices_are_numbered_yymmm_code_serial_reset_monthly():
    series = NumberSeries.objects.get(document_type="tax_invoice")
    assert series.format == "{YY}{MMM}_{IC}_{XX}"
    assert series.reset_period == "monthly"
    assert series.when_full == "grow"


def test_the_35th_w1_invoice_of_september_2026_is_26sep_w1_35():
    assert invoice() == "26SEP_W1_01"
    NumberCounter.objects.filter(division__code="WS").update(last_number=34)
    assert invoice() == "26SEP_W1_35"


def test_the_serial_restarts_each_month_separately_for_each_division():
    assert invoice("WS") == "26SEP_W1_01"
    assert invoice("WS") == "26SEP_W1_02"
    assert invoice("IM") == "26SEP_P1_01"
    assert invoice("WS", date(2026, 10, 1)) == "26OCT_W1_01"
    assert invoice("WS", date(2026, 9, 30)) == "26SEP_W1_03"


def test_after_99_invoices_in_a_month_the_serial_carries_on():
    invoice()
    NumberCounter.objects.filter(division__code="WS").update(last_number=99)
    assert invoice() == "26SEP_W1_100"
    assert invoice() == "26SEP_W1_101"


@pytest.mark.parametrize("month, letters", list(enumerate(numbering.MONTHS, start=1)))
def test_the_month_is_always_three_english_capital_letters(month, letters):
    assert invoice(on_date=date(2026, month, 1)) == f"26{letters}_W1_01"


def test_an_invoice_for_a_division_without_a_tax_invoice_code_is_refused():
    with pytest.raises(NumberSeriesError, match="no tax invoice code"):
        invoice("HO")


def test_the_longest_invoice_number_fits_the_40_character_limit():
    Division.objects.filter(code="HO").update(tax_invoice_code="A" * 15)
    number = invoice("HO")
    assert number == "26SEP_AAAAAAAAAAAAAAA_01"
    assert len(number) <= 40 and " " not in number


# --- Each division's tax invoice code ---------------------------------------------------


def test_the_admin_sets_a_division_tax_invoice_code(admin):
    response = change_division(admin, "HO", tax_invoice_code="h1")
    assert response.status_code == 200, response.json()
    assert response.json()["tax_invoice_code"] == "H1"
    assert invoice("HO") == "26SEP_H1_01"


@pytest.mark.parametrize("value, why", [("W 1", "letters or digits"), ("A" * 16, "letters")])
def test_a_tax_invoice_code_must_be_1_to_15_letters_or_digits(admin, value, why):
    response = change_division(admin, "HO", tax_invoice_code=value)
    assert response.status_code == 400
    assert why in response.json()["detail"]


def test_two_divisions_cannot_share_a_tax_invoice_code(admin):
    response = change_division(admin, "HO", tax_invoice_code="W1")
    assert response.status_code == 400
    assert "already used" in response.json()["detail"]


def test_a_tax_invoice_code_can_be_set_after_vouchers_but_not_changed_after_invoices(admin):
    with transaction.atomic():
        allocate("voucher", division=division("WS"), on_date=SEP)
    assert change_division(admin, "WS", tax_invoice_code="W2").status_code == 200
    invoice("WS")
    response = change_division(admin, "WS", tax_invoice_code="W3")
    assert response.status_code == 400
    assert "cannot change" in response.json()["detail"]
    assert division("WS").tax_invoice_code == "W2"
    listed = {d["code"]: d for d in as_user(admin).get("/api/v1/settings/divisions/").json()}
    assert listed["WS"]["tax_invoice_code_in_use"] is True


def test_the_database_refuses_changing_a_tax_invoice_code_used_on_invoices():
    invoice("WS")
    with pytest.raises(DatabaseError), transaction.atomic():
        Division.objects.filter(code="WS").update(tax_invoice_code="W9")


# --- Quotations QL + YYMMDD + daily count ------------------------------------------------


def test_the_5th_quotation_of_21_october_2026_is_ql26102105():
    numbers = [quotation(date(2026, 10, 21)) for _ in range(5)]
    assert numbers[-1] == "QL26102105"
    assert quotation(date(2026, 10, 22)) == "QL26102201"


def test_quotations_carry_on_after_99_in_a_day():
    quotation(date(2026, 10, 21))
    NumberCounter.objects.filter(series__document_type="quotation").update(last_number=99)
    assert quotation(date(2026, 10, 21)) == "QL261021100"


# --- Settings page ----------------------------------------------------------------------


def test_the_settings_page_shows_which_divisions_still_need_a_code(admin):
    rows = as_user(admin).get("/api/v1/settings/number-series/").json()
    [tax] = [row for row in rows if row["document_type"] == "tax_invoice"]
    nexts = {row["division"]: row["next"] for row in tax["next_numbers"]}
    assert nexts["IM"].endswith("_P1_01")
    assert nexts["HO"] == numbering.NO_TAX_INVOICE_CODE


def test_the_admin_chooses_what_happens_when_a_series_is_full(admin):
    voucher = NumberSeries.objects.get(document_type="voucher")
    response = as_user(admin).patch(
        f"/api/v1/settings/number-series/{voucher.pk}/",
        {
            "format": voucher.format,
            "reset_period": "daily",
            "when_full": "grow",
            "reason": "never block vouchers",
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert NumberSeries.objects.get(pk=voucher.pk).when_full == "grow"


@pytest.mark.parametrize(
    "number_format, reset",
    [("{YY}{MMM}_{IC}_{XX}", "monthly"), ("{IC}-{YYYY}{MMM}-{XXXX}", "monthly")],
)
def test_month_letters_and_the_tax_invoice_code_are_accepted(number_format, reset):
    parsed = numbering.check(number_format, reset)
    assert parsed.has_division


def test_month_number_and_letters_together_are_refused():
    with pytest.raises(NumberSeriesError, match="not both"):
        numbering.check("{YY}{MM}{MMM}{XX}", "monthly")
