"""Costing rates for quotations (backlog P15-02, spec 5.1, rule 11)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.models import AuditEvent, Division
from apps.masters import costing_rates
from apps.masters.models import CostingRate, Material, MaterialRate
from apps.masters.services import MastersError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive")


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", divisions=["WS"])


@pytest.fixture
def en8(accountant):
    return costing_rates.create_material(
        accountant,
        {
            "code": "en8-bar",
            "name": "EN8 steel bar",
            "kind": "metal",
            "form": "round_bar",
            "grade": "EN8 / 080M40",
            "density": "7.850",
        },
    )


def ws():
    return Division.objects.get(code="WS")


# --- Materials --------------------------------------------------------------------------


def test_the_accountant_adds_materials(accountant, en8):
    assert en8.code == "EN8-BAR"  # codes are kept in capitals
    assert en8.density == Decimal("7.850")
    resin = costing_rates.create_material(
        accountant, {"code": "PP-H110", "name": "Polypropylene H110", "kind": "resin"}
    )
    assert resin.form == "other" and resin.density is None
    assert AuditEvent.objects.filter(event="material_created").count() == 2


@pytest.mark.parametrize(
    "values, why",
    [
        ({"code": "", "name": "X", "kind": "metal"}, "material code"),
        ({"code": "X1", "name": "", "kind": "metal"}, "name is required"),
        ({"code": "X1", "name": "X", "kind": "wood"}, "kind of material"),
        ({"code": "X1", "name": "X", "kind": "metal", "form": "cube"}, "form of the material"),
        ({"code": "X1", "name": "X", "kind": "metal", "density": "0"}, "more than 0"),
        ({"code": "X1", "name": "X", "kind": "metal", "density": "7.8501"}, "3 decimal places"),
    ],
)
def test_wrong_material_details_are_refused(accountant, values, why):
    with pytest.raises(MastersError, match=why):
        costing_rates.create_material(accountant, values)


def test_material_codes_are_unique_and_fixed_once_used(accountant, en8):
    with pytest.raises(MastersError, match="already a material EN8-BAR"):
        costing_rates.create_material(accountant, {"code": "EN8-BAR", "name": "X", "kind": "metal"})
    Material.objects.filter(pk=en8.pk).update(first_used_at=timezone.now())  # a quotation used it
    with pytest.raises(DatabaseError, match="code cannot change"), transaction.atomic():
        Material.objects.filter(pk=en8.pk).update(code="EN8")
    with pytest.raises(DatabaseError, match="cannot be deleted"), transaction.atomic():
        Material.objects.filter(pk=en8.pk).delete()


def test_deactivating_a_material_needs_a_reason(accountant, en8):
    with pytest.raises(MastersError, match="Give a reason"):
        costing_rates.update_material(accountant, en8, {"is_active": False})
    costing_rates.update_material(accountant, en8, {"is_active": False}, "No longer stocked")
    en8.refresh_from_db()
    assert not en8.is_active
    with pytest.raises(MastersError, match="inactive"):
        costing_rates.add_material_rate(accountant, en8, effective_from=TODAY, rate="420.00")


# --- Material prices --------------------------------------------------------------------


def test_a_price_starts_today_or_later_and_the_price_of_each_date_is_kept(accountant, en8):
    with pytest.raises(MastersError, match="cannot start in the past"):
        costing_rates.add_material_rate(
            accountant, en8, effective_from=TODAY - timedelta(days=1), rate="400.00"
        )
    # Prices from earlier dates (as if entered back then).
    MaterialRate.objects.create(material=en8, effective_from=TODAY - timedelta(days=60), rate=380)
    MaterialRate.objects.create(material=en8, effective_from=TODAY - timedelta(days=10), rate=400)
    costing_rates.add_material_rate(
        accountant, en8, effective_from=TODAY + timedelta(days=5), rate="425.50"
    )
    assert costing_rates.material_rate_on(en8, TODAY - timedelta(days=30)) == Decimal("380.00")
    assert costing_rates.material_rate_on(en8, TODAY) == Decimal("400.00")
    assert costing_rates.material_rate_on(en8, TODAY + timedelta(days=5)) == Decimal("425.50")
    assert costing_rates.material_rate_on(en8, TODAY - timedelta(days=90)) is None


def test_a_price_in_force_cannot_be_changed_or_removed(accountant, en8):
    old = MaterialRate.objects.create(material=en8, effective_from=TODAY, rate=400)
    with pytest.raises(DatabaseError, match="cannot be changed or removed"), transaction.atomic():
        MaterialRate.objects.filter(pk=old.pk).update(rate=1)
    with pytest.raises(MastersError, match="already in force"):
        costing_rates.remove_material_rate(accountant, old, "typo")
    future = costing_rates.add_material_rate(
        accountant, en8, effective_from=TODAY + timedelta(days=3), rate="410"
    )
    with pytest.raises(MastersError, match="Give a reason"):
        costing_rates.remove_material_rate(accountant, future, "")
    costing_rates.remove_material_rate(accountant, future, "Supplier withdrew the offer")
    assert not MaterialRate.objects.filter(pk=future.pk).exists()


@pytest.mark.parametrize(
    "rate, why", [("-1", "cannot be negative"), ("10.005", "2 decimal places"), ("x", "number")]
)
def test_wrong_prices_are_refused(accountant, en8, rate, why):
    with pytest.raises(MastersError, match=why):
        costing_rates.add_material_rate(accountant, en8, effective_from=TODAY, rate=rate)


def test_one_price_per_material_and_date(accountant, en8):
    costing_rates.add_material_rate(accountant, en8, effective_from=TODAY, rate="400")
    with pytest.raises(MastersError, match="already has a price from"):
        costing_rates.add_material_rate(accountant, en8, effective_from=TODAY, rate="401")


# --- Division rates ---------------------------------------------------------------------


def test_division_costing_rates_by_date(accountant):
    CostingRate.objects.create(
        division=ws(),
        effective_from=TODAY - timedelta(days=30),
        overhead_pct=20,
        margin_pct=25,
        setup_rate=1500,
    )
    new = costing_rates.add_costing_rate(
        accountant,
        ws(),
        effective_from=TODAY + timedelta(days=1),
        overhead_pct="22.50",
        margin_pct="30",
        setup_rate="1750.00",
        reason="New electricity tariff",
    )
    assert costing_rates.costing_rate_on(ws(), TODAY).overhead_pct == Decimal("20.00")
    assert costing_rates.costing_rate_on(ws(), TODAY + timedelta(days=1)) == new
    assert costing_rates.costing_rate_on(Division.objects.get(code="IM"), TODAY) is None
    with pytest.raises(MastersError, match="already has costing rates"):
        costing_rates.add_costing_rate(
            accountant,
            ws(),
            effective_from=TODAY + timedelta(days=1),
            overhead_pct="1",
            margin_pct="1",
            setup_rate="1",
        )


def test_division_rates_in_force_are_kept_as_they_were(accountant):
    rate = CostingRate.objects.create(
        division=ws(), effective_from=TODAY, overhead_pct=20, margin_pct=25, setup_rate=1500
    )
    with pytest.raises(DatabaseError, match="cannot be changed or removed"), transaction.atomic():
        CostingRate.objects.filter(pk=rate.pk).delete()
    with pytest.raises(MastersError, match="cannot start in the past"):
        costing_rates.add_costing_rate(
            accountant,
            ws(),
            effective_from=TODAY - timedelta(days=1),
            overhead_pct="20",
            margin_pct="25",
            setup_rate="1500",
        )
    with pytest.raises(MastersError, match="overhead % cannot be negative"):
        costing_rates.add_costing_rate(
            accountant,
            ws(),
            effective_from=TODAY + timedelta(days=2),
            overhead_pct="-5",
            margin_pct="25",
            setup_rate="1500",
        )


def test_only_the_accountant_maintains_rates(executive, en8):
    with pytest.raises(MastersError, match="Only the Accountant"):
        costing_rates.create_material(executive, {"code": "X", "name": "X", "kind": "metal"})
    with pytest.raises(MastersError, match="Only the Accountant"):
        costing_rates.add_material_rate(executive, en8, effective_from=TODAY, rate="1")


# --- API --------------------------------------------------------------------------------


def test_sales_staff_see_the_rates_but_cannot_change_them(executive, accountant, en8):
    costing_rates.add_material_rate(accountant, en8, effective_from=TODAY, rate="400.00")
    client = as_user(executive)
    materials = client.get("/api/v1/costing/materials/").json()
    assert [(m["code"], m["current_rate"]) for m in materials] == [("EN8-BAR", "400.00")]
    assert client.get("/api/v1/costing/division-rates/").status_code == 200
    refused = client.post(
        f"/api/v1/costing/materials/{en8.pk}/rates/",
        {"effective_from": str(TODAY), "rate": "1"},
        format="json",
    )
    assert refused.status_code == 403


def test_people_without_sales_or_accounting_access_see_nothing(clerk):
    assert as_user(clerk).get("/api/v1/costing/materials/").status_code == 403
    assert as_user(clerk).get("/api/v1/costing/division-rates/").status_code == 403


def test_the_accountant_keeps_rates_through_the_api(accountant):
    client = as_user(accountant)
    made = client.post(
        "/api/v1/costing/materials/",
        {"code": "MB-BLACK", "name": "Black masterbatch", "kind": "masterbatch"},
        format="json",
    )
    assert made.status_code == 201
    pk = made.json()["id"]
    price = client.post(
        f"/api/v1/costing/materials/{pk}/rates/",
        {"effective_from": str(TODAY + timedelta(days=7)), "rate": "1250.00", "reason": "Quote"},
        format="json",
    )
    assert price.status_code == 201 and price.json()["in_force"] is False
    removed = client.delete(
        f"/api/v1/costing/materials/{pk}/rates/{price.json()['id']}/",
        {"reason": "Entered twice"},
        format="json",
    )
    assert removed.status_code == 204

    division = client.post(
        "/api/v1/costing/division-rates/",
        {
            "division": "im",
            "effective_from": str(TODAY),
            "overhead_pct": "18",
            "margin_pct": "22.5",
            "setup_rate": "1200",
        },
        format="json",
    )
    assert division.status_code == 201
    assert division.json()["division"] == "IM" and division.json()["current"] is True
    assert division.json()["margin_pct"] == "22.50"
