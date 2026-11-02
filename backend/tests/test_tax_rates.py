"""Tax rates in a control panel: the Admin or the Accountant enters, the Director confirms
(backlog P16-20; owner's decision of 2 Nov 2026)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode, TaxComponent, TaxRate
from apps.accounting.services import AccountingError
from apps.core.access import effective_access

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
GO_LIVE = date(2024, 1, 1)


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def sscl_m():
    return TaxComponent.objects.get(code="SSCL-M")


@pytest.fixture
def in_use(accountant):
    """SSCL-M at 2.125% since go-live, already used on a document."""
    taxes.add_rate(accountant, sscl_m(), effective_from=GO_LIVE, rate="2.125")
    taxes.add_rate(
        accountant, TaxComponent.objects.get(code="VAT"), effective_from=GO_LIVE, rate="18"
    )
    taxes.mark_used(sscl_m())
    return sscl_m()


def test_three_sscl_taxes_printed_as_sscl():
    rows = {c.code: c.label for c in TaxComponent.objects.filter(code__startswith="SSCL")}
    assert rows == {"SSCL": "SSCL", "SSCL-M": "SSCL", "SSCL-R": "SSCL"}
    assert effective_access(person("d@sml.lk", "director")).can("confirm_tax_rates")


def test_a_change_takes_effect_only_when_the_director_confirms(admin, director, in_use):
    later = TODAY + timedelta(days=10)
    change = taxes.propose_rate(
        admin, in_use, effective_from=later, rate="2.5", reason="Gazette 2499/01"
    )
    assert change.status == "pending"
    assert taxes.rate_on(in_use, later).rate == Decimal("2.1250")  # not yet
    with pytest.raises(AccountingError, match="Only the Director"):
        taxes.confirm_rate(person("acc@sml.lk", "accountant"), change)
    taxes.confirm_rate(director, change)
    assert taxes.rate_on(in_use, later).rate == Decimal("2.5000")
    assert taxes.rate_on(in_use, TODAY).rate == Decimal("2.1250")  # old documents keep theirs
    result = taxes.calculate(TaxCode.objects.get(code="VAT-SSCL-M"), "1000.00", later)
    assert result.lines[0].amount == Decimal("25.00")


def test_proposals_are_checked(admin, accountant, director, in_use):
    clerk = person("clerk@sml.lk", "clerk")
    with pytest.raises(AccountingError, match="Only the Admin or the Accountant"):
        taxes.propose_rate(clerk, in_use, effective_from=TODAY, rate="2", reason="x")
    with pytest.raises(AccountingError, match="Give the reason"):
        taxes.propose_rate(admin, in_use, effective_from=TODAY, rate="2", reason="")
    with pytest.raises(AccountingError, match="in the past"):
        taxes.propose_rate(
            admin, in_use, effective_from=TODAY - timedelta(days=1), rate="2", reason="x"
        )
    with pytest.raises(AccountingError, match="between 0 and 100"):
        taxes.propose_rate(admin, in_use, effective_from=TODAY, rate="250", reason="x")
    first = taxes.propose_rate(accountant, in_use, effective_from=TODAY, rate="2", reason="x")
    with pytest.raises(AccountingError, match="already has a change waiting"):
        taxes.propose_rate(admin, in_use, effective_from=TODAY, rate="3", reason="y")
    with pytest.raises(AccountingError, match="Only the person who entered"):
        taxes.withdraw_rate(admin, first)
    taxes.withdraw_rate(accountant, first)
    second = taxes.propose_rate(admin, in_use, effective_from=TODAY, rate="3", reason="y")
    with pytest.raises(AccountingError, match="reason"):
        taxes.reject_rate(director, second, "")
    taxes.reject_rate(director, second, "Not in the gazette")
    assert taxes.rate_on(in_use, TODAY).rate == Decimal("2.1250")
    with pytest.raises(DatabaseError), transaction.atomic():
        TaxRate.objects.filter(pk=second.pk).update(status="confirmed")
    # Someone who is both Admin and Director still cannot confirm their own change.
    both = person("both@sml.lk", "system_admin", "director")
    third = taxes.propose_rate(both, in_use, effective_from=TODAY, rate="2.2", reason="z")
    with pytest.raises(AccountingError, match="you entered yourself"):
        taxes.confirm_rate(both, third)


def test_a_used_tax_is_not_changed_around_the_director(accountant, in_use):
    with pytest.raises(AccountingError, match="Settings → Tax rates"):
        taxes.add_rate(accountant, in_use, effective_from=TODAY + timedelta(days=5), rate="3")
    rate = in_use.rates.get()
    with pytest.raises(AccountingError, match="add a new rate instead"):
        taxes.remove_rate(accountant, rate, reason="typo")


def test_the_control_panel(admin, director, in_use):
    page = as_user(admin).get("/api/v1/settings/tax-rates/").json()
    assert (page["can_propose"], page["can_confirm"]) == (True, False)
    row = next(t for t in page["taxes"] if t["code"] == "SSCL-M")
    assert (row["printed_as"], row["current"]["rate"]) == ("SSCL", "2.125")
    made = as_user(admin).post(
        "/api/v1/settings/tax-rates/",
        {
            "component": in_use.pk,
            "effective_from": TODAY.isoformat(),
            "rate": "2.5",
            "reason": "Gazette",
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    pending = next(t for t in made.json()["taxes"] if t["code"] == "SSCL-M")["pending"][0]
    assert pending["created_by_me"] is True
    boss = as_user(director)
    assert boss.get("/api/v1/settings/tax-rates/").json()["can_confirm"] is True
    done = boss.post(f"/api/v1/settings/tax-rates/{pending['id']}/confirm/")
    assert done.status_code == 200, done.json()
    row = next(t for t in done.json()["taxes"] if t["code"] == "SSCL-M")
    assert row["current"]["rate"] == "2.5" and row["pending"] == []
    clerk = person("clerk@sml.lk", "clerk")
    assert as_user(clerk).get("/api/v1/settings/tax-rates/").status_code == 403
