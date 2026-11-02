"""Quotation approval limits (backlog P0-12, spec 3A.3)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError, IntegrityError
from django.utils import timezone

from apps.core.models import AuditEvent, Division
from apps.masters import currencies, limits
from apps.masters.models import Currency, QuotationLimit

from .test_access import as_user, person

pytestmark = pytest.mark.django_db


def today():
    return timezone.localdate()


def ws():
    return Division.objects.get(code="WS")


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def propose(user, start=None, margin="20", value="1000000", division=None):
    return limits.propose(
        user=user,
        division=division or ws(),
        effective_from=start or today(),
        min_margin_pct=margin,
        director_above_lkr=value,
        reason="owner's policy",
    )


# --- Proposing and confirming -----------------------------------------------------------


def test_a_change_by_the_admin_has_no_effect_until_the_director_confirms(admin, director):
    pending = propose(admin)
    assert limits.in_force(ws(), today()) is None
    limits.confirm(director, pending)
    current = limits.in_force(ws(), today())
    assert current.pk == pending.pk
    assert (current.min_margin_pct, current.director_above_lkr) == (
        Decimal("20.00"),
        Decimal("1000000.00"),
    )
    assert AuditEvent.objects.filter(event="quotation_limit_confirmed").exists()


def test_only_the_director_confirms_and_never_their_own_change(admin, director):
    pending = propose(admin)
    with pytest.raises(limits.LimitError, match="Only the Director"):
        limits.confirm(admin, pending)
    accountant = person("accountant@sml.lk", "accountant")
    with pytest.raises(limits.LimitError, match="Only the Director"):
        limits.confirm(accountant, pending)
    # A Director who is also given Settings: Manage still cannot confirm their own entry.
    own = limits.withdraw(admin, pending)
    assert own.status == "withdrawn"
    director_entry = QuotationLimit.objects.create(
        division=ws(),
        effective_from=today(),
        min_margin_pct=Decimal("10"),
        director_above_lkr=Decimal("500000"),
        created_by=director,
    )
    with pytest.raises(limits.LimitError, match="yourself"):
        limits.confirm(director, director_entry)


def test_the_director_can_reject_with_a_reason(admin, director):
    pending = propose(admin)
    with pytest.raises(limits.LimitError, match="reason"):
        limits.reject(director, pending, "")
    rejected = limits.reject(director, pending, "margin too low for moulding")
    assert rejected.status == "rejected"
    assert limits.in_force(ws(), today()) is None


def test_one_change_at_a_time_per_division(admin):
    propose(admin)
    with pytest.raises(limits.LimitError, match="already has a change waiting"):
        propose(admin, start=today() + timedelta(days=5))
    propose(admin, division=Division.objects.get(code="IM"), margin="15")


@pytest.mark.parametrize(
    "margin, value, days, why",
    [
        ("100", "1000000", 0, "below 100%"),
        ("-1", "1000000", 0, "from 0%"),
        ("20.125", "1000000", 0, "2 decimal"),
        ("abc", "1000000", 0, "number"),
        ("20", "0", 0, "more than zero"),
        ("20", "1000000", -1, "past"),
    ],
)
def test_limits_must_be_valid(admin, margin, value, days, why):
    with pytest.raises(limits.LimitError, match=why):
        propose(admin, start=today() + timedelta(days=days), margin=margin, value=value)


def test_a_change_confirmed_after_its_date_takes_effect_from_the_confirmation(admin, director):
    pending = propose(admin, start=today())
    QuotationLimit.objects.filter(pk=pending.pk).update(effective_from=today() - timedelta(days=3))
    confirmed = limits.confirm(director, QuotationLimit.objects.get(pk=pending.pk))
    assert confirmed.effective_from == today()


# --- History and dates ------------------------------------------------------------------


def test_old_quotations_keep_the_limits_of_their_date(admin, director):
    limits.confirm(director, propose(admin, margin="20"))
    later = today() + timedelta(days=30)
    limits.confirm(director, propose(admin, start=later, margin="25"))
    assert limits.in_force(ws(), today()).min_margin_pct == Decimal("20.00")
    assert limits.in_force(ws(), later).min_margin_pct == Decimal("25.00")
    assert QuotationLimit.objects.filter(division=ws(), status="confirmed").count() == 2


def test_a_confirmed_limit_can_never_be_changed_or_deleted(admin, director):
    confirmed = limits.confirm(director, propose(admin))
    with pytest.raises(DatabaseError), transaction.atomic():
        QuotationLimit.objects.filter(pk=confirmed.pk).update(min_margin_pct=Decimal("5"))
    with pytest.raises(DatabaseError), transaction.atomic():
        QuotationLimit.objects.filter(pk=confirmed.pk).delete()


def test_a_pending_change_cannot_be_edited_in_the_database(admin):
    pending = propose(admin)
    with pytest.raises(DatabaseError), transaction.atomic():
        QuotationLimit.objects.filter(pk=pending.pk).update(director_above_lkr=Decimal("9"))


def test_two_confirmed_limits_cannot_start_on_the_same_day(admin, director):
    limits.confirm(director, propose(admin))
    second = propose(admin)
    with pytest.raises(limits.LimitError, match="already has confirmed limits"):
        limits.confirm(director, second)
    with pytest.raises(IntegrityError), transaction.atomic():
        QuotationLimit.objects.filter(pk=second.pk).update(status="confirmed")


# --- What a quotation will check (Phase 1.5) --------------------------------------------


def test_a_quotation_needs_the_director_below_the_margin_or_above_the_value(admin, director):
    limits.confirm(director, propose(admin, margin="20", value="1000000"))
    fine = limits.check_quotation(division=ws(), on_date=today(), margin_pct="22", value="900000")
    assert not fine.needs_director
    low = limits.check_quotation(division=ws(), on_date=today(), margin_pct="18.5", value="900000")
    assert low.needs_director
    assert low.reasons == ["Margin 18.5% is below the minimum of 20.00%."]
    big = limits.check_quotation(
        division=ws(), on_date=today(), margin_pct="25", value="1000000.01"
    )
    assert big.reasons == ["Value LKR 1,000,000.01 is above LKR 1,000,000.00."]


def test_a_foreign_currency_quotation_is_converted_at_the_rate_of_its_date(admin, director):
    limits.confirm(director, propose(admin, value="1000000"))
    currencies.set_rate(currency=Currency.objects.get(code="USD"), on_date=today(), rate="300")
    check = limits.check_quotation(
        division=ws(), on_date=today(), margin_pct="25", value="3400", currency="USD"
    )
    assert check.value_lkr == Decimal("1020000.00")
    assert check.needs_director


def test_without_confirmed_limits_the_defaults_apply():
    """Owner, 2 Nov 2026: a minimum margin of 1% and no maximum value."""
    check = limits.check_quotation(
        division=ws(), on_date=today(), margin_pct="1.5", value="999999999"
    )
    assert not check.needs_director and check.reasons == []
    check = limits.check_quotation(division=ws(), on_date=today(), margin_pct="0.5", value="1")
    assert check.reasons == ["Margin 0.5% is below the minimum of 1.00%."]


def test_the_maximum_value_can_be_left_empty(admin, director):
    limits.confirm(director, propose(admin, margin="12", value=""))
    current = limits.in_force(ws(), today())
    assert (current.min_margin_pct, current.director_above_lkr) == (Decimal("12.00"), None)
    assert "no maximum value" in str(current)
    check = limits.check_quotation(
        division=ws(), on_date=today(), margin_pct="15", value="999999999"
    )
    assert check.reasons == []
    with pytest.raises(limits.LimitError, match="more than zero, or left empty"):
        propose(admin, value="0", division=Division.objects.get(code="IM"))


# --- The settings page API --------------------------------------------------------------


def test_the_admin_proposes_and_the_director_confirms_on_the_same_page(admin, director):
    response = as_user(admin).post(
        "/api/v1/settings/quotation-limits/",
        {
            "division": "IM",
            "effective_from": today().isoformat(),
            "min_margin_pct": "15",
            "director_above_lkr": "1000000.00",
            "reason": "agreed at the board meeting",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "pending"
    pk = response.json()["id"]
    assert (
        as_user(admin).post(f"/api/v1/settings/quotation-limits/{pk}/confirm/").status_code == 400
    )
    response = as_user(director).post(f"/api/v1/settings/quotation-limits/{pk}/confirm/")
    assert response.status_code == 200, response.json()
    rows = as_user(director).get("/api/v1/settings/quotation-limits/").json()
    assert rows[0]["status"] == "confirmed" and rows[0]["in_force"] is True
    assert rows[0]["decided_by"] == "director@sml.lk"


def test_only_the_admin_proposes_limits(director):
    clerk = person("clerk@sml.lk", "clerk")
    data = {
        "division": "WS",
        "effective_from": today().isoformat(),
        "min_margin_pct": "20",
        "director_above_lkr": "1000000",
        "reason": "x",
    }
    for user in (clerk, director):
        response = as_user(user).post("/api/v1/settings/quotation-limits/", data, format="json")
        assert response.status_code == 403
    assert as_user(clerk).get("/api/v1/settings/quotation-limits/").status_code == 403
