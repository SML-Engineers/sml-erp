"""Fixed asset register, depreciation and disposals (backlog P2-19)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import services as chart
from apps.accounting.models import DetailType
from apps.assets import services
from apps.assets.models import AssetClass, DepreciationRun, FixedAsset
from apps.assets.services import AssetError, month_end, month_start
from apps.core.models import Division
from apps.masters import banking

from .test_access import as_user, person

pytestmark = pytest.mark.django_db
D = Decimal
TODAY = timezone.localdate()
M2 = month_start(month_start(TODAY) - timedelta(days=1))  # last month
M1 = month_start(M2 - timedelta(days=1))  # the month before


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


def cls(code):
    return AssetClass.objects.get(code=code)


def ws():
    return Division.objects.get(code="WS")


def buy(user, code="PLANT", cost="1200000.00", **extra):
    values = {"name": "CNC lathe", "acquisition_date": M1, "cost": cost} | extra
    return services.register(user, asset_class=cls(code), division=ws(), **values)


def rate(user, code="PLANT", method="straight_line", value="12"):
    return services.add_rate(user, cls(code), effective_from=M1, method=method, rate=value)


def lines_of(entry):
    return sorted(
        (x.account.number, x.division.code if x.division else None, x.debit, x.credit)
        for x in entry.lines.select_related("account", "division")
    )


def test_the_classes_are_loaded_without_rates(accountant):
    assert [c.code for c in AssetClass.objects.all()] == [
        "LAND",
        "BUILDINGS",
        "PLANT",
        "MOULDS",
        "VEHICLES",
        "FURNITURE",
        "COMPUTERS",
    ]
    lathe = buy(accountant)
    assert lathe.code == "FA0001" and lathe.depreciation_from == M1
    with pytest.raises(
        AssetError, match="No depreciation method and rate for: Plant and machinery"
    ):
        services.prepare(accountant, M1)


def test_straight_line_month_by_month(accountant):
    rate(accountant)
    lathe = buy(accountant)
    run = services.prepare(accountant, M1)
    assert [(x.asset, x.amount) for x in run.lines.all()] == [(lathe, D("12000.00"))]
    run = services.post(accountant, run)
    assert lines_of(run.journal_entry) == [
        ("1590", "WS", D("0"), D("12000.00")),
        ("6800", "WS", D("12000.00"), D("0")),
    ]
    assert services.next_month() == month_end(M2)
    with pytest.raises(AssetError, match="next month to depreciate"):
        services.prepare(accountant, month_end(TODAY))
    with pytest.raises(DatabaseError, match="never changes"), transaction.atomic():
        DepreciationRun.objects.filter(pk=run.pk).update(total=D("1"))
    with pytest.raises(DatabaseError, match="fixed"), transaction.atomic():
        FixedAsset.objects.filter(pk=lathe.pk).update(cost=D("1"))
    with pytest.raises(AssetError, match="a new rate starts after it"):
        services.add_rate(
            accountant, cls("PLANT"), effective_from=M1, method="straight_line", rate="10"
        )


def test_reducing_balance_and_the_residual_value(accountant):
    rate(accountant, "VEHICLES", "reducing_balance", "20")
    van = buy(accountant, "VEHICLES", "100000.00", name="Delivery van")
    rate(accountant, "COMPUTERS", "straight_line", "12")
    # Brought in at go-live with 9,900.00 already charged: 50.00 is left above the residual.
    pc = buy(
        accountant,
        "COMPUTERS",
        "10000.00",
        name="Laptop",
        residual_value="50.00",
        opening_accumulated="9900.00",
    )
    services.post(accountant, services.prepare(accountant, M1))
    second = services.prepare(accountant, M2)
    amounts = {x.asset: x.amount for x in second.lines.all()}
    assert amounts[van] == D("1638.89")  # (100,000 − 1,666.67) × 20% ÷ 12
    assert pc not in amounts  # 99.50 a month, capped at the 50.00 left in the first month
    assert services.book_value(pc) == D("50.00")


def test_land_is_never_depreciated(accountant):
    buy(accountant, "LAND", "5000000.00", name="Factory land")
    run = services.prepare(accountant, M1)
    assert not run.lines.exists()


def test_a_disposal_posts_the_gain_or_loss(accountant):
    rate(accountant)
    lathe = buy(accountant)
    bank = banking.create_account(
        accountant,
        code="com-cur",
        kind="current",
        name="Commercial Bank current",
        bank_name="Commercial Bank",
        account_number="1000234567",
        ledger_account=chart.create_account(
            accountant,
            name="Commercial Bank current",
            account_type="bank",
            detail_type=DetailType.objects.get(name="Current account"),
            number="1030",
        ).pk,
    )
    sold = M2 + timedelta(days=4)
    with pytest.raises(AssetError, match="Post the depreciation up to"):
        services.dispose(
            accountant,
            lathe,
            disposed_on=sold,
            proceeds="1150000",
            account=bank,
            reason="Sold to Lanka Engineering",
        )
    services.post(accountant, services.prepare(accountant, M1))
    lathe = services.dispose(
        accountant,
        lathe,
        disposed_on=sold,
        proceeds="1150000",
        account=bank,
        reason="Sold to Lanka Engineering",
    )
    assert lines_of(lathe.disposal_entry) == [
        ("1030", None, D("1150000.00"), D("0")),
        ("1520", "WS", D("0"), D("1200000.00")),
        ("1590", "WS", D("12000.00"), D("0")),
        ("8020", "WS", D("38000.00"), D("0")),
    ]
    assert not services.prepare(accountant, M2).lines.exists()  # gone in the month it went
    with pytest.raises(DatabaseError, match="disposed"), transaction.atomic():
        FixedAsset.objects.filter(pk=lathe.pk).update(name="changed")


def test_through_the_api(accountant):
    client = as_user(accountant)
    classes = client.get("/api/v1/asset-classes/").json()
    plant = next(c for c in classes if c["code"] == "PLANT")
    assert plant["current"] is None
    made = client.post(
        f"/api/v1/asset-classes/{plant['id']}/rates/",
        {"effective_from": str(M1), "method": "straight_line", "rate": "12"},
        format="json",
    )
    assert made.status_code == 201, made.content
    asset = client.post(
        "/api/v1/fixed-assets/",
        {
            "asset_class": plant["id"],
            "division": "WS",
            "name": "CNC lathe",
            "acquisition_date": str(M1),
            "cost": "1200000.00",
        },
        format="json",
    )
    assert asset.status_code == 201, asset.content
    run = client.post("/api/v1/depreciation/", {"month_end": str(month_end(M1))}, format="json")
    assert run.status_code == 201, run.content
    assert run.json()["total"] == "12000.00"
    posted = client.post(f"/api/v1/depreciation/{run.json()['id']}/post/")
    assert posted.json()["status"] == "posted"
