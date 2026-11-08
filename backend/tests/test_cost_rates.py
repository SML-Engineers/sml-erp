"""Production cost rates (backlog P3-05): dated labour, overhead, regrind and mould
amortisation rates kept by the Accountant and read by production planning; labour offered from
the latest approved payroll (a division's rate for a section of fewer than three people);
overhead 0 until set, a machine's rate beating its section's; regrind at 100% of the material's
cost unless set; only company moulds amortised; a rate in force never changes (database); and
the BOM standard cost with labour, overhead and mould amortisation."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.masters import customers
from apps.masters.models import Machine, MachineRate, Section
from apps.payroll.models import Employee
from apps.production import boms, moulds, rates, routings
from apps.production.models import CostRate
from apps.production.rates import RateError

from .test_access import as_user, person
from .test_boms import item, shaft_lines, stock  # noqa: F401
from .test_payroll import close_month, director, hr, kamal, present, working_days  # noqa: F401
from .test_payslips import approved  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/v1/cost-rates/"
LONG_AGO = date(2026, 1, 1)


@pytest.fixture
def accountant():
    return person("acc@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def planner():
    return person("planner@sml.lk", "production_planner", divisions=["WS", "IM"])


@pytest.fixture
def manager():
    return person("pm@sml.lk", "production_manager", divisions=["WS", "IM"])


@pytest.fixture
def lathes():
    section = Section.objects.get(code="M-LAT")
    return [
        Machine.objects.create(code=f"M-LAT-0{n}", name=f"Lathe {n}", section=section)
        for n in (1, 2)
    ]


def tomorrow() -> date:
    return timezone.localdate() + timedelta(days=1)


def old(kind, rate, **target) -> CostRate:
    """A rate already in force (entered directly, as if months ago)."""
    return CostRate.objects.create(
        kind=kind, effective_from=LONG_AGO, rate=D(rate), reason="Opening", **target
    )


def mould(planner, code="MD-001", **more):
    item(planner, f"P-{code}", f"Part {code}")
    values = {"code": code, "name": code, "cycle_time_s": "12", "shot_weight_g": "40"}
    return moulds.create(planner, values | {"parts": f"P-{code} x 8"} | more)


def test_the_accountant_keeps_the_rates_and_production_reads_them(
    accountant, planner, manager, lathes
):
    made = as_user(accountant).post(
        URL,
        {"kind": "labour", "section": "M-LAT", "rate": "450", "reason": "Budget 2026"},
        format="json",
    )
    assert made.status_code == 201, made.json()
    body = made.json()
    lathe = next(s for s in body["sections"] if s["code"] == "M-LAT")
    assert lathe["labour"]["rate"] == "450.00" and lathe["labour"]["source"] == "manual"
    assert lathe["labour"]["effective_from"] == timezone.localdate().isoformat()
    assert body["can_keep"] is True
    assert rates.labour_on(Section.objects.get(code="M-LAT")) == D("450")
    # The Production Manager and Planner read them, but only the Accountant changes them.
    for reader in (planner, manager):
        seen = as_user(reader).get(URL)
        assert seen.status_code == 200 and seen.json()["can_keep"] is False
        refused = as_user(reader).post(
            URL, {"kind": "labour", "section": "M-LAT", "rate": "1"}, format="json"
        )
        assert refused.status_code == 400
        assert "Only the Accountant" in refused.json()["detail"]
    # Someone outside production planning sees nothing (server check, rule 8).
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get(URL).status_code == 403
    assert CostRate.objects.get().created_by == accountant


@pytest.mark.parametrize(
    "values, message",
    [
        ({"kind": "wages"}, "Choose labour, overhead, regrind or mould"),
        ({"kind": "labour", "section": "NOPE"}, "Choose the section"),
        ({"kind": "labour", "rate": ""}, "Give the rate per hour"),
        ({"kind": "labour", "rate": "abc"}, "is a number"),
        ({"kind": "labour", "rate": "-5"}, "at least 0"),
        ({"kind": "labour", "rate": "4.555"}, "at most 2 decimal places"),
        ({"kind": "labour", "reason": ""}, "Give the reason"),
        ({"kind": "labour", "effective_from": "2020-01-01"}, "today or later"),
        ({"kind": "labour", "effective_from": "next week"}, "Give the date"),
        ({"kind": "overhead", "machine": "X-9", "section": ""}, "no machine X-9"),
        ({"kind": "regrind", "material": "SH-100"}, "not a raw material counted in kg"),
        ({"kind": "regrind", "material": "NONE-1"}, "no item NONE-1"),
        ({"kind": "mould", "mould": "MD-404"}, "no mould MD-404"),
    ],
)
def test_rates_are_checked(accountant, planner, stock, values, message):  # noqa: F811
    base = {"section": "M-LAT", "rate": "100", "reason": "Budget"}
    with pytest.raises(RateError, match=message):
        rates.add(accountant, base | values)
    assert not CostRate.objects.exists()


def test_a_rate_in_force_never_changes(accountant, lathes):
    section = Section.objects.get(code="M-LAT")
    in_force = old("labour", "400", section=section)
    # The database refuses to change or delete it; saving it unchanged is allowed.
    in_force.save()
    for change in (
        lambda: CostRate.objects.filter(pk=in_force.pk).update(rate=D("1")),
        lambda: CostRate.objects.filter(pk=in_force.pk).delete(),
    ):
        with pytest.raises(DatabaseError, match="never changes"), transaction.atomic():
            change()
    with pytest.raises(RateError, match="in force: add a new one"):
        rates.remove(accountant, in_force)
    # A second rate for today is refused once one is in force from today.
    rates.add(accountant, {"kind": "labour", "section": "M-LAT", "rate": "420", "reason": "A"})
    with pytest.raises(RateError, match="already has a rate in force"):
        rates.add(accountant, {"kind": "labour", "section": "M-LAT", "rate": "430", "reason": "B"})
    # A future rate is replaced on the same date, and can be taken back before it.
    later = {"kind": "labour", "section": "M-LAT", "effective_from": tomorrow().isoformat()}
    first = rates.add(accountant, later | {"rate": "500", "reason": "New wages"})
    second = rates.add(accountant, later | {"rate": "510", "reason": "Corrected"})
    assert first.pk == second.pk and second.rate == D("510")
    assert rates.labour_on(section) == D("420")
    assert rates.labour_on(section, tomorrow()) == D("510")
    gone = as_user(accountant).delete(f"{URL}{second.pk}/")
    assert gone.status_code == 200
    assert not CostRate.objects.filter(pk=second.pk).exists()
    assert as_user(accountant).delete(f"{URL}{in_force.pk}/").status_code == 400


def test_overhead_is_zero_until_set_and_a_machine_beats_its_section(accountant, lathes):
    section = Section.objects.get(code="M-LAT")
    one, two = lathes
    assert rates.overhead_on(section) == D("0")
    assert rates.overhead_on(section, one) == D("0")
    rates.add(accountant, {"kind": "overhead", "section": "M-LAT", "rate": "200", "reason": "A"})
    rates.add(accountant, {"kind": "overhead", "machine": "M-LAT-01", "rate": "350", "reason": "B"})
    assert rates.overhead_on(section) == D("200")
    assert rates.overhead_on(section, one) == D("350")
    assert rates.overhead_on(section, two) == D("200")
    body = as_user(accountant).get(URL).json()
    by = {m["code"]: m for m in body["machines"]}
    assert by["M-LAT-01"]["in_force"] == "350.00" and by["M-LAT-02"]["in_force"] == "200.00"
    assert by["M-LAT-01"]["section"] == "M-LAT"
    # The database keeps a machine's rate under its own section.
    with pytest.raises(DatabaseError, match="its own section"), transaction.atomic():
        CostRate.objects.create(
            kind="overhead",
            section=Section.objects.get(code="M-MIL"),
            machine=one,
            effective_from=tomorrow(),
            rate=D("1"),
            reason="Wrong",
        )
    # Retired machines take no new rate.
    Machine.objects.filter(pk=two.pk).update(status=Machine.Status.RETIRED)
    with pytest.raises(RateError, match="retired"):
        rates.add(
            accountant, {"kind": "overhead", "machine": "M-LAT-02", "rate": "1", "reason": "x"}
        )


def test_regrind_is_credited_at_the_material_cost_unless_set(accountant, planner, monkeypatch):
    resin = item(planner, "PP-H", "PP homopolymer", "raw_material", "kg")
    beads = item(planner, "PP-G", "PP in grams", "raw_material", "g")
    stock_cost = {resin.pk: D("520.50"), beads.pk: D("0.5205")}
    monkeypatch.setattr(rates, "cost_of", lambda material: stock_cost.get(material.pk, D("0")))
    # 100% of the original material's cost (owner, 7 Nov 2026), per kg.
    assert rates.regrind_on(resin) == {"per_kg": D("520.5000"), "basis": "material"}
    assert rates.regrind_on(beads)["per_kg"] == D("520.5000")
    stock_cost[resin.pk] = D("0")
    assert rates.regrind_on(resin) == {"per_kg": None, "basis": "material"}
    # The Accountant can set a dated value per kg instead.
    rates.add(accountant, {"kind": "regrind", "material": "PP-H", "rate": "300", "reason": "Sold"})
    assert rates.regrind_on(resin) == {"per_kg": D("300.00"), "basis": "set"}
    body = as_user(accountant).get(URL).json()
    by = {m["code"]: m for m in body["materials"]}
    assert by["PP-H"]["per_kg"] == "300.00" and by["PP-H"]["basis"] == "set"
    assert by["PP-G"]["basis"] == "material"


def test_only_company_moulds_are_amortised(accountant, planner):
    own = mould(planner)
    values = {"kind": "mould", "mould": "MD-001", "reason": "Bought 2025"}
    with pytest.raises(RateError, match="expected life in shots"):
        rates.add(accountant, values | {"mould_cost": "1500000", "life_shots": "0"})
    with pytest.raises(RateError, match="whole number of shots"):
        rates.add(accountant, values | {"mould_cost": "1500000", "life_shots": "1.5"})
    assert rates.mould_on(own) == D("0")  # 0 until entered
    saved = rates.add(accountant, values | {"mould_cost": "1,500,000", "life_shots": "1,000,000"})
    assert (saved.rate, saved.mould_cost, saved.life_shots) == (D("1.5"), D("1500000"), 1000000)
    assert rates.mould_on(own) == D("1.5")
    body = as_user(accountant).get(URL).json()
    assert body["moulds"][0]["rate"]["rate"] == "1.5000"
    assert body["moulds"][0]["life_shots"] == 1000000
    # A customer's mould is never amortised: the service and the database refuse it.
    sales = person("sales@sml.lk", "sales_executive", all_divisions=True)
    buyer = customers.create_customer(sales, {"name": "Lanka Bottlers"}, confirmed=True)
    theirs = mould(planner, "MD-010", owner="customer", customer=buyer.code)
    with pytest.raises(RateError, match="customer's mould"):
        rates.add(accountant, values | {"mould": "MD-010", "mould_cost": "1", "life_shots": "1"})
    with pytest.raises(DatabaseError, match="Only company moulds"), transaction.atomic():
        CostRate.objects.create(
            kind="mould",
            mould=theirs,
            effective_from=tomorrow(),
            rate=D("1"),
            mould_cost=D("1"),
            life_shots=1,
            reason="x",
        )
    assert rates.mould_on(theirs) == D("0")
    assert [m["code"] for m in body["moulds"]] == ["MD-001"]


def test_labour_is_offered_from_the_latest_approved_payroll(
    accountant,
    planner,
    approved,  # noqa: F811
    monkeypatch,
):
    lathe = Section.objects.get(code="M-LAT")
    Employee.objects.filter(pk__in=[x.employee_id for x in approved.lines.all()]).update(
        section=lathe
    )
    # Two people only: the division's rate is offered, so nobody's pay shows.
    offered = rates.suggestions()[lathe.pk]
    division_rate = rates.labour.rate(approved.division, approved.month)
    assert offered["per_hour"] == division_rate and offered["basis"] == "division"
    # The Planner sees the rates in force but not the payroll's figures.
    planned = as_user(planner).get(URL).json()
    assert next(s for s in planned["sections"] if s["code"] == "M-LAT")["payroll"] is None
    body = as_user(accountant).get(URL).json()
    row = next(s for s in body["sections"] if s["code"] == "M-LAT")
    assert row["payroll"] == {
        "per_hour": f"{division_rate:.2f}",
        "basis": "division",
        "payroll": "WS Oct 2026",
    }
    # Accepting it makes a dated rate that remembers the payroll it came from.
    accepted = as_user(accountant).post(f"{URL}accept/", {"sections": ["M-LAT"]}, format="json")
    assert accepted.status_code == 200, accepted.json()
    rate = CostRate.objects.get(kind="labour", section=lathe)
    assert (rate.rate, rate.source, rate.payroll_run) == (division_rate, "payroll", approved)
    assert rate.reason == "Payroll WS Oct 2026 (division rate)"
    with pytest.raises(RateError, match="has a labour rate for M-MIL"):
        rates.accept(accountant, {"sections": ["M-MIL"], "effective_from": tomorrow().isoformat()})
    # With enough people in the section, its own rate is offered; "accept all" takes it.
    monkeypatch.setattr(rates, "MIN_PEOPLE", 2)
    own = rates.suggestions()[lathe.pk]
    assert own["basis"] == "section"
    rates.accept(accountant, {"effective_from": tomorrow().isoformat()})
    assert rates.labour_on(lathe, tomorrow()) == own["per_hour"]
    with pytest.raises(RateError, match="Only the Accountant"):
        rates.accept(planner, {})


def test_no_payroll_no_offer(accountant):
    assert rates.suggestions() == {}
    with pytest.raises(RateError, match="No approved payroll"):
        rates.accept(accountant, {})


def test_the_bom_cost_adds_labour_overhead_and_mould_amortisation(
    accountant,
    planner,
    manager,
    stock,  # noqa: F811
):
    section = Section.objects.get(code="M-LAT")
    lathe = Machine.objects.create(code="M-LAT-01", name="Lathe 1", section=section)
    MachineRate.objects.create(
        machine=lathe, effective_from=LONG_AGO, rate=D("3000"), created_by=planner
    )
    routing = routings.create(
        planner,
        {
            "item": "SH-100",
            "operations": [
                {"name": "Turn", "machine": "M-LAT-01", "run_min": "12"},
                {"name": "Mill", "section": "M-MIL", "run_min": "6"},
            ],
        },
    )
    routings.submit(planner, routing)
    routings.decide(manager, routing, "approve")
    bom = boms.create(planner, {"item": "SH-100", "lines": shaft_lines()})
    c = boms.cost(bom)
    # No labour rates yet: listed, never guessed; overhead 0 until set.
    assert "SH-100 op 10: no labour rate for M-LAT" in c["missing"]
    assert "SH-100 op 20: no labour rate for M-MIL" in c["missing"]
    assert (c["labour"], c["overhead"], c["mould"]) == (D("0"), D("0"), D("0"))
    old("labour", "400", section=section)
    old("labour", "500", section=Section.objects.get(code="M-MIL"))
    old("overhead", "250", section=section)
    old("overhead", "600", section=section, machine=lathe)
    c = boms.cost(bom)
    assert c["labour"] == D("130.00")  # 12 min at 400 + 6 min at 500 an hour
    assert c["overhead"] == D("120.00")  # 12 min at the lathe's own 600 an hour; M-MIL 0
    assert c["machine"] == D("600.00")  # 12 min at 3,000 (M-MIL has no machine rate)
    assert c["per_unit"] == D("1300.00")  # 450 plating + 600 + 130 + 120
    assert not [m for m in c["missing"] if "labour" in m]
    body = as_user(planner).get(f"/api/v1/boms/{bom.pk}/").json()
    assert body["cost"] | {"missing": []} == {
        "material": "450.00",
        "machine": "600.00",
        "labour": "130.00",
        "overhead": "120.00",
        "mould": "0.00",
        "per_unit": "1300.00",
        "missing": [],
    }
    # Earlier days keep the rates in force then (rule 11).
    assert boms.cost(bom, day=date(2025, 12, 31))["labour"] == D("0")


def test_moulding_boms_carry_the_mould_amortisation(accountant, planner):
    item(planner, "CAP-28", "Cap 28 mm")
    item(planner, "LID-90", "Lid 90 mm")
    item(planner, "PP-H", "PP homopolymer", "raw_material", "kg")
    base = {"cycle_time_s": "12", "shot_weight_g": "40", "runner_weight_g": "4"}
    single = moulds.create(planner, base | {"code": "MD-001", "name": "Cap", "parts": "CAP-28 x 8"})
    family = moulds.create(
        planner, base | {"code": "MD-002", "name": "Family", "parts": "CAP-28 x 4; LID-90 x 2"}
    )
    for m in (single, family):
        CostRate.objects.create(
            kind="mould",
            mould=m,
            effective_from=LONG_AGO,
            rate=D("2"),
            mould_cost=D("2000000"),
            life_shots=1000000,
            reason="Opening",
        )
    lines = [{"line_type": "raw", "component": "PP-H"}]
    caps = boms.create(
        planner,
        {
            "item": "CAP-28",
            "kind": "moulding",
            "mould": "MD-001",
            "base_quantity": "1000",
            "outputs": [{"item": "CAP-28", "cavities": 8, "part_weight_g": "4"}],
            "lines": lines,
        },
    )
    assert boms.cost(caps)["mould"] == D("0.25")  # LKR 2 a shot over 8 caps
    shot = boms.create(
        planner,
        {
            "item": "LID-90",
            "kind": "moulding",
            "mould": "MD-002",
            "outputs": [
                {"item": "CAP-28", "cavities": 4, "part_weight_g": "4"},
                {"item": "LID-90", "cavities": 2, "part_weight_g": "10"},
            ],
            "lines": lines,
        },
    )
    assert boms.cost(shot)["mould"] == D("2.00")  # a family mould's BOM is per shot
