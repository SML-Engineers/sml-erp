"""Currencies and exchange rates (backlog P0-11, spec 3A.4)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.masters import currencies
from apps.masters.models import Currency, ExchangeRate
from apps.masters.services import MastersError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db


def today():
    return timezone.localdate()


def days_ago(n):
    return today() - timedelta(days=n)


def usd():
    return Currency.objects.get(code="USD")


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


# --- Currencies -------------------------------------------------------------------------


def test_lkr_is_the_base_and_common_currencies_are_preloaded():
    codes = list(Currency.objects.values_list("code", flat=True))
    assert codes[0] == "LKR"
    assert set(codes) == {"LKR", "USD", "EUR", "GBP", "AUD", "JPY", "CNY", "INR", "SGD", "AED"}
    assert Currency.objects.get(code="LKR").is_base
    assert Currency.objects.get(code="JPY").decimal_places == 0


def test_the_admin_switches_a_currency_off_with_a_reason_and_adds_another(admin):
    client = as_user(admin)
    url = "/api/v1/settings/currencies/AED/"
    assert client.patch(url, {"is_active": False}, format="json").status_code == 400
    response = client.patch(url, {"is_active": False, "reason": "no UAE customers"}, format="json")
    assert response.status_code == 200
    assert "AED" not in [c["code"] for c in client.get("/api/v1/currencies/").json()]
    response = client.post(
        "/api/v1/settings/currencies/",
        {"code": "chf", "name": "Swiss franc", "symbol": "CHF", "decimal_places": 2},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["code"] == "CHF"
    assert AuditEvent.objects.filter(event="currency_switched_off").exists()


@pytest.mark.parametrize(
    "data, why",
    [
        ({"code": "US"}, "3-letter"),
        ({"code": "USD"}, "already in the list"),
        ({"decimal_places": 5}, "0 to 4"),
        ({"name": ""}, "name is required"),
    ],
)
def test_a_new_currency_must_be_valid(data, why):
    base = {"code": "CHF", "name": "Swiss franc", "decimal_places": 2}
    with pytest.raises(MastersError, match=why):
        currencies.create_currency(**(base | data))


def test_lkr_cannot_be_switched_off_or_changed():
    lkr = Currency.objects.get(code="LKR")
    with pytest.raises(MastersError, match="base currency"):
        currencies.update_currency(lkr, {"is_active": False}, reason="x")
    with pytest.raises(DatabaseError), transaction.atomic():
        Currency.objects.filter(code="LKR").update(is_active=False)
    with pytest.raises(DatabaseError), transaction.atomic():
        Currency.objects.filter(code="USD").update(is_base=True)


def test_only_the_admin_manages_the_currency_list(accountant):
    response = as_user(accountant).post(
        "/api/v1/settings/currencies/", {"code": "CHF", "name": "Swiss franc"}, format="json"
    )
    assert response.status_code == 403


# --- Rates ------------------------------------------------------------------------------


def test_the_accountant_enters_a_daily_rate_exactly(accountant):
    response = as_user(accountant).post(
        "/api/v1/settings/exchange-rates/",
        {"currency": "USD", "date": today().isoformat(), "rate": "299.123456"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert ExchangeRate.objects.get().rate == Decimal("299.123456")
    assert response.json()["rate"] == "299.123456"


def test_with_buying_and_selling_only_the_middle_rate_is_used():
    rate = currencies.set_rate(currency=usd(), on_date=today(), buying="296.50", selling="303.25")
    assert rate.rate == Decimal("299.875000")


@pytest.mark.parametrize(
    "data, why",
    [
        ({"rate": "0"}, "more than zero"),
        ({"rate": "-3"}, "more than zero"),
        ({"rate": "abc"}, "number"),
        ({"rate": "1.1234567"}, "6 decimal"),
        ({"rate": None, "buying": "300"}, "both the buying and selling"),
        ({"rate": "300", "buying": "305", "selling": "301"}, "cannot be above"),
    ],
)
def test_a_rate_must_be_valid(data, why):
    with pytest.raises(MastersError, match=why):
        currencies.set_rate(currency=usd(), on_date=today(), **data)


def test_no_rates_for_lkr_or_for_future_dates():
    with pytest.raises(MastersError, match="base currency"):
        currencies.set_rate(currency=Currency.objects.get(code="LKR"), on_date=today(), rate="1")
    with pytest.raises(MastersError, match="future"):
        currencies.set_rate(currency=usd(), on_date=today() + timedelta(days=1), rate="300")


def test_correcting_a_rate_needs_a_reason_and_is_audited():
    currencies.set_rate(currency=usd(), on_date=today(), rate="300")
    with pytest.raises(MastersError, match="reason"):
        currencies.set_rate(currency=usd(), on_date=today(), rate="301")
    currencies.set_rate(currency=usd(), on_date=today(), rate="301", reason="typing error")
    assert ExchangeRate.objects.get().rate == Decimal("301")
    [row] = AuditEvent.objects.filter(event="exchange_rate_corrected")
    assert row.reason == "typing error"


def test_only_the_accountant_enters_rates_but_everyone_can_read_them(admin, accountant):
    data = {"currency": "USD", "date": today().isoformat(), "rate": "300"}
    clerk = person("clerk@sml.lk", "clerk")
    for user in (admin, clerk):
        assert (
            as_user(user).post("/api/v1/settings/exchange-rates/", data, format="json").status_code
            == 403
        )
    as_user(accountant).post("/api/v1/settings/exchange-rates/", data, format="json")
    assert len(as_user(clerk).get("/api/v1/settings/exchange-rates/").json()) == 1


# --- Using a rate -----------------------------------------------------------------------


def test_a_document_uses_the_rate_of_its_date():
    currencies.set_rate(currency=usd(), on_date=days_ago(3), rate="298.00")
    currencies.set_rate(currency=usd(), on_date=days_ago(1), rate="300.00")
    lookup = currencies.rate_on("USD", days_ago(1))
    assert lookup.rate == Decimal("300.00") and not lookup.carried_forward


def test_without_a_rate_for_the_day_the_latest_earlier_rate_is_used_and_flagged(accountant):
    currencies.set_rate(currency=usd(), on_date=days_ago(3), rate="298.00")
    lookup = currencies.rate_on("USD", days_ago(1))
    assert lookup.rate == Decimal("298.00")
    assert lookup.rate_date == days_ago(3)
    assert lookup.carried_forward
    response = as_user(accountant).get(
        "/api/v1/exchange-rates/lookup/", {"currency": "USD", "date": days_ago(1).isoformat()}
    )
    assert response.json()["carried_forward"] is True
    assert response.json()["rate_date"] == days_ago(3).isoformat()


def test_no_rate_at_all_is_refused_with_a_clear_message():
    with pytest.raises(MastersError, match="no USD rate on or before"):
        currencies.rate_on("USD", today())


def test_lkr_converts_at_one_and_others_round_to_the_cent():
    assert currencies.rate_on("LKR", today()).rate == Decimal("1")
    currencies.set_rate(currency=usd(), on_date=today(), rate="299.875")
    lookup = currencies.rate_on("USD", today())
    assert currencies.to_lkr(Decimal("1234.56"), lookup) == Decimal("370213.68")


def test_a_rate_used_on_a_document_can_never_change():
    currencies.set_rate(currency=usd(), on_date=today(), rate="300")
    currencies.mark_rate_used(currencies.rate_on("USD", today()))
    with pytest.raises(MastersError, match="used on documents"):
        currencies.set_rate(currency=usd(), on_date=today(), rate="301", reason="x")
    with pytest.raises(MastersError, match="cannot be removed"):
        currencies.delete_rate(ExchangeRate.objects.get(), reason="x")
    with pytest.raises(DatabaseError), transaction.atomic():
        ExchangeRate.objects.update(rate=Decimal("1"))
    with pytest.raises(DatabaseError), transaction.atomic():
        ExchangeRate.objects.all().delete()


# --- CSV import -------------------------------------------------------------------------


def upload(user, text, reason="CBSL rates", dry_run=False):
    return as_user(user).post(
        "/api/v1/settings/exchange-rates/import/",
        {
            "file": SimpleUploadedFile("rates.csv", text.encode()),
            "reason": reason,
            "dry_run": "1" if dry_run else "",
        },
        format="multipart",
    )


def test_rates_are_imported_from_csv(accountant):
    d1, d2 = days_ago(2).isoformat(), days_ago(1).isoformat()
    text = (
        f"date,currency,rate,buying,selling\n"
        f"{d1},USD,299.50,,\n"
        f"{d2},usd,,296.00,304.00\n"
        f"{d2},EUR,325.10,,\n"
    )
    response = upload(accountant, text)
    assert response.status_code == 200, response.json()
    assert response.json() == {"dry_run": False, "added": 3, "corrected": 0, "unchanged": 0}
    assert currencies.rate_on("USD", days_ago(1)).rate == Decimal("300.000000")
    assert ExchangeRate.objects.filter(source="import").count() == 3


def test_a_trial_import_saves_nothing(accountant):
    text = f"date,currency,rate\n{today().isoformat()},USD,300\n"
    response = upload(accountant, text, dry_run=True)
    assert response.json()["added"] == 1
    assert not ExchangeRate.objects.exists()


def test_an_import_with_a_bad_line_saves_nothing_and_lists_every_problem(accountant):
    text = (
        "date,currency,rate\n"
        f"{today().isoformat()},USD,300\n"
        "2026/10/01,EUR,325\n"
        f"{today().isoformat()},XYZ,1\n"
        f"{today().isoformat()},LKR,1\n"
    )
    response = upload(accountant, text)
    assert response.status_code == 400
    assert response.json()["errors"] == [
        "Line 3: Date '2026/10/01' must be written as YYYY-MM-DD.",
        "Line 4: Unknown currency XYZ.",
        "Line 5: LKR is the base currency; it has no exchange rate.",
    ]
    assert not ExchangeRate.objects.exists()


def test_an_import_needs_a_reason_and_the_right_columns(accountant):
    assert upload(accountant, "date,currency,rate\n", reason="").status_code == 400
    response = upload(accountant, "when,what\n2026-10-01,USD\n")
    assert response.status_code == 400
    assert "date, currency, rate" in response.json()["errors"][0]
