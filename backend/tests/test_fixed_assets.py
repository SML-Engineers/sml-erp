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
from apps.assets.models import AssetClass, AssetClassRate, AssetTerms, DepreciationRun, FixedAsset
from apps.assets.services import AssetError, month_end, month_start
from apps.core.models import Division, User
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


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def the_director():
    found = User.objects.filter(email="dir@sml.lk").first()
    return found or person("dir@sml.lk", "director", all_divisions=True)


def approve_all(director):
    """The Director approves every class default and asset terms waiting."""
    for r in AssetClassRate.objects.filter(status="awaiting"):
        services.decide_rate(director, r, "approve")
    for t in AssetTerms.objects.filter(status="awaiting"):
        services.decide_terms(director, t, "approve")


def cls(code):
    return AssetClass.objects.get(code=code)


def ws():
    return Division.objects.get(code="WS")


def buy(user, code="PLANT", cost="1200000.00", **extra):
    values = {"name": "CNC lathe", "acquisition_date": M1, "cost": cost} | extra
    asset = services.register(user, asset_class=cls(code), division=ws(), **values)
    approve_all(the_director())
    return asset


def rate(user, code="PLANT", method="straight_line", value="12"):
    made = services.add_rate(user, cls(code), effective_from=M1, method=method, rate=value)
    approve_all(the_director())
    return made


def lines_of(entry):
    return sorted(
        (x.account.number, x.division.code if x.division else None, x.debit, x.credit)
        for x in entry.lines.select_related("account", "division")
    )


def test_the_classes_carry_the_owners_defaults(accountant, director):
    assert [c.code for c in AssetClass.objects.all()] == [
        "LAND",
        "BUILDINGS",
        "PLANT",
        "MOULDS",
        "VEHICLES",
        "FURNITURE",
        "COMPUTERS",
    ]
    defaults = {
        c.code: (r.method, r.rate, r.life_years)
        for c in AssetClass.objects.all()
        for r in [services.rate_on(c, TODAY)]
    }
    assert defaults == {
        "LAND": ("none", D("0"), None),
        "BUILDINGS": ("straight_line", D("5"), 20),
        "PLANT": ("straight_line", D("10"), 10),
        "MOULDS": ("straight_line", D("10"), 10),
        "VEHICLES": ("straight_line", D("20"), 5),
        "FURNITURE": ("straight_line", D("25"), 4),
        "COMPUTERS": ("straight_line", D("25"), 4),
    }
    # A new asset takes its class's defaults and waits for the Director.
    lathe = services.register(
        accountant,
        asset_class=cls("PLANT"),
        division=ws(),
        name="CNC lathe",
        acquisition_date=M1,
        cost="1200000.00",
    )
    assert lathe.code == "FA0001" and lathe.depreciation_from == M1
    terms = lathe.terms.get()
    assert (terms.status, terms.method, terms.rate, terms.life_years) == (
        "awaiting",
        "straight_line",
        D("10"),
        10,
    )
    with pytest.raises(AssetError, match="No approved depreciation terms for: FA0001"):
        services.prepare(accountant, M1)
    with pytest.raises(AssetError):
        services.decide_terms(accountant, terms, "approve")  # the Accountant cannot
    services.decide_terms(director, terms, "approve")
    run = services.prepare(accountant, M1)
    assert [x.amount for x in run.lines.all()] == [D("10000.00")]  # 1,200,000 × 10% ÷ 12


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
    assert plant["current"]["life_years"] == 10
    made = client.post(
        f"/api/v1/asset-classes/{plant['id']}/rates/",
        {"effective_from": str(M1), "method": "straight_line", "rate": "12"},
        format="json",
    )
    assert made.status_code == 201, made.content
    approve_all(the_director())
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
    assert asset.json()["terms"]["rate"] == "12"
    approve_all(the_director())
    run = client.post("/api/v1/depreciation/", {"month_end": str(month_end(M1))}, format="json")
    assert run.status_code == 201, run.content
    assert run.json()["total"] == "12000.00"
    posted = client.post(f"/api/v1/depreciation/{run.json()['id']}/post/")
    assert posted.json()["status"] == "posted"


def test_the_accountant_changes_one_assets_terms_and_the_director_approves(accountant, director):
    lathe = services.register(
        accountant,
        asset_class=cls("PLANT"),
        division=ws(),
        name="Old lathe",
        acquisition_date=M1,
        cost="600000.00",
        life_years="5",
        method="straight_line",
        terms_reason="Bought second hand",
    )
    terms = lathe.terms.get()
    assert (terms.rate, terms.life_years, terms.reason) == (D("20"), 5, "Bought second hand")
    services.decide_terms(director, terms, "approve")
    run = services.prepare(accountant, M1)
    assert run.lines.get().amount == D("10000.00")  # 600,000 × 20% ÷ 12
    services.post(accountant, run)
    # A change starts after the last posted month and waits for the Director again.
    with pytest.raises(AssetError, match="new terms start after it"):
        services.propose_terms(accountant, lathe, effective_from=M1, life_years="4",
                               method="straight_line")  # fmt: skip
    later = services.propose_terms(
        accountant, lathe, effective_from=M2, method="straight_line", life_years="4",
        reason="Heavier use",
    )  # fmt: skip
    with pytest.raises(AssetError, match="already has terms waiting"):
        services.propose_terms(accountant, lathe, effective_from=M2, method="straight_line",
                               rate="10")  # fmt: skip
    assert services.terms_on(lathe, month_end(M2)).rate == D("20")  # not yet approved
    services.decide_terms(director, later, "reject", "Keep five years")
    later.refresh_from_db()
    assert later.status == "rejected"
    # Terms never change once sent, and are never deleted (database).
    with pytest.raises(DatabaseError, match="never change once sent"), transaction.atomic():
        AssetTerms.objects.filter(pk=terms.pk).update(rate=D("1"))
    with pytest.raises(DatabaseError, match="never deleted"), transaction.atomic():
        AssetTerms.objects.filter(pk=terms.pk).delete()


@pytest.mark.parametrize(
    "values, message",
    [
        ({"method": "sum_of_digits"}, "Choose the method"),
        ({"method": "straight_line", "rate": "", "life_years": ""}, "Give the useful life"),
        ({"method": "straight_line", "rate": "10", "life_years": "1"}, "1 years is 100.00%"),
        ({"method": "straight_line", "life_years": "0"}, "1 to 100 years"),
        ({"method": "straight_line", "life_years": "2.5"}, "whole number of years"),
        ({"method": "reducing_balance", "rate": ""}, "Give the rate"),
        ({"method": "reducing_balance", "rate": "120"}, "from 0 to 100"),
        ({"method": "reducing_balance", "rate": "abc"}, "not a number"),
    ],
)
def test_terms_are_checked(accountant, values, message):
    with pytest.raises(AssetError, match=message):
        services.add_rate(accountant, cls("PLANT"), effective_from=M2, **values)


def test_class_defaults_need_the_director(accountant, director):
    made = services.add_rate(
        accountant, cls("PLANT"), effective_from=M2, method="straight_line", life_years="8",
        reason="Auditors' advice",
    )  # fmt: skip
    assert (made.status, made.rate) == ("awaiting", D("12.5"))
    assert services.rate_on(cls("PLANT"), M2).rate == D("10")  # not yet in force
    with pytest.raises(AssetError):
        services.decide_rate(accountant, made, "approve")
    services.decide_rate(director, made, "approve")
    assert services.rate_on(cls("PLANT"), M2).rate == D("12.5")


def test_assets_from_before_get_their_class_defaults_approved_once(accountant, director):
    old = buy(accountant)
    # An asset registered before terms existed has none until "send all".
    other = FixedAsset.objects.create(
        code="FA0099",
        name="Generator",
        asset_class=cls("PLANT"),
        division=ws(),
        acquisition_date=M1,
        depreciation_from=M1,
        cost=D("500000"),
        created_by=accountant,
    )
    assert services.send_all(accountant) == 1
    assert other.terms.get().status == "awaiting" and old.terms.get().status == "approved"
    assert services.send_all(accountant) == 0


def test_approvals_through_the_api(accountant, director):
    services.register(
        accountant, asset_class=cls("PLANT"), division=ws(), name="Press brake",
        acquisition_date=M1, cost="900000.00",
    )  # fmt: skip
    waiting = as_user(director).get("/api/v1/fixed-assets/waiting/").json()
    row = waiting["terms"][0]
    assert (row["asset_name"], row["rate"], row["life_years"], row["can_decide"]) == (
        "Press brake",
        "10",
        10,
        True,
    )
    assert (
        as_user(accountant).get("/api/v1/fixed-assets/waiting/").json()["terms"][0]["can_decide"]
        is False
    )
    done = as_user(director).post(
        f"/api/v1/fixed-assets/terms/{row['id']}/decide/", {"action": "approve"}, format="json"
    )
    assert done.status_code == 200 and done.json()["status"] == "approved"
    plant = next(c for c in as_user(accountant).get("/api/v1/asset-classes/").json()
                 if c["code"] == "PLANT")  # fmt: skip
    asked = as_user(accountant).post(
        f"/api/v1/asset-classes/{plant['id']}/rates/",
        {"effective_from": str(M2), "method": "straight_line", "life_years": "8"},
        format="json",
    )
    assert asked.status_code == 201, asked.content
    rate_id = as_user(director).get("/api/v1/fixed-assets/waiting/").json()["rates"][0]["id"]
    decided = as_user(director).post(
        f"/api/v1/asset-classes/rates/{rate_id}/decide/",
        {"action": "reject", "reason": "Stay with 10 years"},
        format="json",
    )
    assert decided.json()["status"] == "rejected"
