"""Machining costing of quotation lines (backlog P15-04, spec 5.1, rule 11)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.models import AuditEvent, Division, Role
from apps.masters import costing_rates, currencies, customers
from apps.masters import services as masters
from apps.masters.models import Currency, Machine, Section
from apps.sales import costing, services
from apps.sales.costing import CostingInput, ExtraInput, OperationInput
from apps.sales.models import Quotation, QuotationCosting
from apps.sales.services import BreakInput, LineInput, SalesError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
TOMORROW = TODAY + timedelta(days=1)


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def other_executive():
    return person("sales2@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def manager():
    return person("salesmanager@sml.lk", "sales_manager", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def unilever(executive):
    return customers.create_customer(executive, {"name": "Unilever Sri Lanka"})


@pytest.fixture
def rates(accountant):
    """What the Accountant has entered, in force from today: EN8 bar at LKR 450 per kg, and
    for the Workshop 15% overhead, 20% margin and LKR 1,500 per setup hour."""
    en8 = costing_rates.create_material(
        accountant,
        {
            "code": "EN8",
            "name": "EN8 steel bar",
            "kind": "metal",
            "form": "round_bar",
            "density": "7.850",
        },
    )
    costing_rates.add_material_rate(accountant, en8, effective_from=TODAY, rate="450")
    costing_rates.add_costing_rate(
        accountant,
        Division.objects.get(code="WS"),
        effective_from=TODAY,
        overhead_pct="15",
        margin_pct="20",
        setup_rate="1500",
    )
    return en8


def machine(code, section_code, rate):
    m = masters.create_machine(code=code, section=Section.objects.get(code=section_code), name=code)
    masters.add_rate(m, effective_from=TODAY, rate=rate)
    return m


@pytest.fixture
def lathe():
    return machine("C-LAT-01", "C-LAT", "3000")


@pytest.fixture
def mill():
    return machine("M-MIL-01", "M-MIL", "2400")


def quotation(user, customer, *, price="3000", breaks=(("50", "2700"),), **values):
    return services.save(
        user,
        None,
        customer=customer,
        division=Division.objects.get(code="WS"),
        lines=[
            LineInput(
                description="Shaft, EN8, turned and milled",
                quantity="10",
                unit_price=price,
                breaks=[BreakInput(q, p) for q, p in breaks],
            )
        ],
        **values,
    )


def shaft(en8, lathe, mill, **extra) -> CostingInput:
    """Ø50 EN8 bar, 100 mm per piece plus 5 mm for the saw and facing; turning 12 minutes,
    milling 6; 2 setup hours; heat treatment LKR 85 a piece and transport LKR 2,000 a
    delivery."""
    return CostingInput(
        **{
            "material": en8,
            "size_a_mm": "50",
            "length_mm": "100",
            "cutting_allowance_mm": "5",
            "setup_hours": "2",
            "operations": [
                OperationInput(lathe, "12", "Turn"),
                OperationInput(mill, "6", "Mill flats"),
            ],
            "extras": [
                ExtraInput("Heat treatment", "85"),
                ExtraInput("Transport", "2000", per_order=True),
            ],
        }
        | extra
    )


@pytest.fixture
def costed(executive, unilever, rates, lathe, mill):
    q = quotation(executive, unilever)
    costing.save(executive, q, 1, shaft(rates, lathe, mill))
    return q


def results(q):
    line = q.lines.get(line_no=1)
    return costing.results(line.costing, line, q.exchange_rate)


# --- Working out the price --------------------------------------------------------------


def test_the_build_up_gives_the_suggested_price_and_the_margin_quoted(costed):
    at_10, at_50 = results(costed)
    # Material: π/4 × 50² × 105 mm × 7.85 g/cm³ = 1.6184 kg × 450 = 728.28
    assert costed.lines.get().costing.weight_kg == Decimal("1.6184")
    assert at_10["material"] == Decimal("728.28")
    assert at_10["machining"] == Decimal("840.00")  # 12 min at 3,000/h + 6 min at 2,400/h
    assert at_10["setup"] == Decimal("300.00")  # 2 h × 1,500 ÷ 10 pieces
    assert at_10["subcontract"] == Decimal("285.00")  # 85 + 2,000 ÷ 10
    assert at_10["direct_cost"] == Decimal("2153.28")
    assert at_10["overhead"] == Decimal("322.99")  # 15%
    assert at_10["cost"] == Decimal("2476.27")
    assert at_10["margin"] == Decimal("495.25")  # 20% on the cost
    assert at_10["suggested_price_lkr"] == Decimal("2971.52")
    assert at_10["quoted_margin_pct"] == Decimal("21.15")  # quoted at 3,000
    assert at_10["below_cost"] is False


def test_each_quantity_break_shares_setup_and_transport_over_its_own_quantity(costed):
    at_50 = results(costed)[1]
    assert at_50["quantity"] == Decimal("50.000")
    assert (at_50["setup"], at_50["subcontract"]) == (Decimal("60.00"), Decimal("125.00"))
    assert at_50["cost"] == Decimal("2016.27")
    assert at_50["suggested_price_lkr"] == Decimal("2419.52")
    assert at_50["quoted_margin_pct"] == Decimal("33.91")  # quoted at 2,700


def test_a_price_below_cost_is_flagged(executive, unilever, rates, lathe, mill):
    q = quotation(executive, unilever, price="2000", breaks=())
    costing.save(executive, q, 1, shaft(rates, lathe, mill))
    (at_10,) = results(q)
    assert at_10["below_cost"] is True
    assert at_10["quoted_margin_pct"] < 0


def test_overhead_and_margin_can_be_changed_for_the_line(executive, unilever, rates, lathe, mill):
    q = quotation(executive, unilever)
    saved = costing.save(
        executive, q, 1, shaft(rates, lathe, mill, overhead_pct="10", margin_pct="12.5")
    )
    assert (saved.overhead_pct, saved.margin_pct) == (Decimal("10.00"), Decimal("12.50"))
    at_10 = results(q)[0]
    assert at_10["cost"] == Decimal("2368.61")  # 2,153.28 + 215.33
    assert at_10["margin"] == Decimal("296.08")


def test_an_export_quotation_is_costed_in_lkr_and_priced_in_its_currency(
    executive, unilever, rates, lathe, mill
):
    currencies.set_rate(currency=Currency.objects.get(code="EUR"), on_date=TODAY, rate="325.40")
    q = quotation(executive, unilever, price="9.50", breaks=(), currency="EUR")
    costing.save(executive, q, 1, shaft(rates, lathe, mill))
    (at_10,) = results(q)
    assert at_10["cost"] == Decimal("2476.27")  # LKR
    assert at_10["suggested_price"] == Decimal("9.13")  # 2,971.52 ÷ 325.40, in EUR
    assert at_10["quoted_price_lkr"] == Decimal("3091.30")
    assert at_10["quoted_margin_pct"] == Decimal("24.84")


@pytest.mark.parametrize(
    "form, density, sizes, kg",
    [
        ("hex_bar", "8.500", {"size_a_mm": "24", "length_mm": "60"}, "0.2544"),
        ("tube", "7.850", {"size_a_mm": "60", "size_b_mm": "40", "length_mm": "200"}, "2.4662"),
        ("plate", "2.700", {"size_a_mm": "20", "size_b_mm": "50", "length_mm": "100"}, "0.2700"),
    ],
)
def test_weight_from_the_size_of_bars_tubes_and_plates(
    executive, unilever, rates, accountant, form, density, sizes, kg
):
    material = costing_rates.create_material(
        accountant,
        {
            "code": f"T-{form}".replace("_", "-"),
            "name": form,
            "kind": "metal",
            "form": form,
            "density": density,
        },
    )
    costing_rates.add_material_rate(accountant, material, effective_from=TODAY, rate="100")
    q = quotation(executive, unilever)
    saved = costing.save(executive, q, 1, CostingInput(material=material, **sizes))
    assert saved.weight_kg == Decimal(kg)


def test_a_weight_entered_is_used_and_material_can_be_left_out(executive, unilever, rates):
    q = quotation(executive, unilever)
    saved = costing.save(executive, q, 1, CostingInput(material=rates, weight_kg="2.5"))
    assert saved.weight_kg == Decimal("2.5000")
    assert results(q)[0]["material"] == Decimal("1125.00")
    free_issue = costing.save(executive, q, 1, CostingInput(setup_hours="1"))
    assert free_issue.material is None and free_issue.weight_kg == 0
    assert results(q)[0]["material"] == Decimal("0.00")


@pytest.mark.parametrize(
    "change, why",
    [
        ({"size_a_mm": None}, "diameter"),
        ({"length_mm": ""}, "length of stock"),
        ({"setup_hours": "1.234"}, "2 decimal places"),
        ({"margin_pct": "-5"}, "cannot be negative"),
        ({"size_a_mm": 50.0}, "exact number"),
        ({"operations": [OperationInput(None, "5")]}, "choose the machine"),
        ({"extras": [ExtraInput("", "10")]}, "say what it is"),
    ],
)
def test_wrong_costing_is_refused(executive, unilever, rates, lathe, mill, change, why):
    q = quotation(executive, unilever)
    with pytest.raises(SalesError, match=why):
        costing.save(executive, q, 1, shaft(rates, lathe, mill, **change))


def test_a_minute_count_must_be_more_than_zero(executive, unilever, rates, lathe):
    q = quotation(executive, unilever)
    with pytest.raises(SalesError, match="Operation 1: The minutes per piece must be more"):
        costing.save(executive, q, 1, CostingInput(operations=[OperationInput(lathe, "0")]))


def test_machines_of_another_division_or_retired_ones_are_refused(executive, unilever, rates):
    press = machine("IM-01", "IM-MLD", "4000")
    q = quotation(executive, unilever)
    with pytest.raises(SalesError, match="not a working machine of WS"):
        costing.save(executive, q, 1, CostingInput(operations=[OperationInput(press, "1")]))
    old = machine("M-MIL-09", "M-MIL", "1000")
    Machine.objects.filter(pk=old.pk).update(status=Machine.Status.RETIRED)
    old.refresh_from_db()
    with pytest.raises(SalesError, match="not a working machine"):
        costing.save(executive, q, 1, CostingInput(operations=[OperationInput(old, "1")]))


def test_missing_rates_are_explained(executive, unilever, accountant):
    q = quotation(executive, unilever)
    with pytest.raises(SalesError, match="no costing rates for WS"):
        costing.save(executive, q, 1, CostingInput())
    costing_rates.add_costing_rate(
        accountant,
        Division.objects.get(code="WS"),
        effective_from=TODAY,
        overhead_pct="15",
        margin_pct="20",
        setup_rate="1500",
    )
    unpriced = costing_rates.create_material(
        accountant, {"code": "SS304", "name": "Stainless", "kind": "metal"}
    )
    with pytest.raises(SalesError, match="SS304 has no price per kg"):
        costing.save(executive, q, 1, CostingInput(material=unpriced, weight_kg="1"))
    unrated = masters.create_machine(
        code="C-LAT-02", section=Section.objects.get(code="C-LAT"), name="Lathe 2"
    )
    with pytest.raises(SalesError, match="C-LAT-02 has no hourly rate"):
        costing.save(executive, q, 1, CostingInput(operations=[OperationInput(unrated, "1")]))


# --- Rates of the quotation's date (rule 11) --------------------------------------------


def test_the_costing_keeps_the_rates_of_the_quotation_date(costed, accountant, rates, lathe):
    # New rates from tomorrow do not touch a quotation made today.
    costing_rates.add_material_rate(accountant, rates, effective_from=TOMORROW, rate="900")
    masters.add_rate(lathe, effective_from=TOMORROW, rate="9000")
    costing_rates.add_costing_rate(
        accountant,
        Division.objects.get(code="WS"),
        effective_from=TOMORROW,
        overhead_pct="50",
        margin_pct="50",
        setup_rate="5000",
    )
    saved = costed.lines.get().costing
    assert (saved.rates_date, saved.material_rate, saved.setup_rate) == (
        TODAY,
        Decimal("450.00"),
        Decimal("1500.00"),
    )
    assert saved.operations.get(seq=1).rate == Decimal("3000.00")
    assert results(costed)[0]["suggested_price_lkr"] == Decimal("2971.52")


def test_materials_and_machines_used_keep_their_codes(costed, rates, lathe, mill):
    for record in (rates, lathe, mill):
        record.refresh_from_db()
        assert record.first_used_at is not None


# --- Lines keep their costing when the draft is saved -----------------------------------


def test_saving_the_draft_keeps_the_costing_of_its_lines(costed, executive):
    first = costed.lines.get()
    new_line = LineInput(description="Bush", quantity="5", unit_price="800")
    kept = LineInput(id=first.id, description=first.description, quantity="20", unit_price="2900")
    services.save(executive, costed, lines=[new_line, kept])
    bush, shaft_line = costed.lines.order_by("line_no")
    assert (bush.description, shaft_line.line_no) == ("Bush", 2)
    assert shaft_line.costing.material_rate == Decimal("450.00")
    assert not QuotationCosting.objects.filter(line=bush).exists()
    # The figures follow the new quantity: setup 3,000 ÷ 20 pieces.
    at_20 = costing.results(shaft_line.costing, shaft_line, costed.exchange_rate)[0]
    assert at_20["setup"] == Decimal("150.00")


def test_a_line_left_out_loses_its_costing_and_drawings_follow_their_line(costed, executive):
    first = costed.lines.get()
    services.add_file(executive, costed, SimpleUploadedFile("shaft.pdf", b"%PDF-1 a"), 1)
    second = services.save(
        executive,
        costed,
        lines=[
            LineInput(id=first.id, description="Shaft", quantity="10", unit_price="3000"),
            LineInput(description="Bush", quantity="5", unit_price="800"),
        ],
    ).lines.get(line_no=2)
    services.add_file(executive, costed, SimpleUploadedFile("bush.pdf", b"%PDF-1 b"), 2)
    # The shaft is removed: the bush becomes line 1 and its drawing goes with it.
    services.save(
        executive,
        costed,
        lines=[LineInput(id=second.id, description="Bush", quantity="5", unit_price="800")],
    )
    assert QuotationCosting.objects.filter(line__quotation=costed).count() == 0
    files = {f.file_name: f.line_no for f in costed.files.all()}
    assert files == {"shaft.pdf": None, "bush.pdf": 1}


def test_a_line_of_another_quotation_cannot_be_sent(costed, executive, unilever):
    other = quotation(executive, unilever)
    stranger = other.lines.get()
    with pytest.raises(SalesError, match="not part of this quotation"):
        services.save(
            executive,
            costed,
            lines=[LineInput(id=stranger.id, description="X", quantity="1", unit_price="1")],
        )


# --- Who sees and changes the costing (owner's decision, 31 Oct 2026) -------------------


def test_who_sees_the_costing(costed, executive, other_executive, manager, director, accountant):
    assert costing.can_see(executive, costed)  # the creator
    assert costing.can_see(manager, costed)
    assert costing.can_see(director, costed)
    assert costing.can_see(accountant, costed)
    assert not costing.can_see(other_executive, costed)
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert not costing.can_see(clerk, costed)


def test_the_api_gives_costing_only_to_those_who_may_see_it(
    costed, executive, other_executive, manager, accountant, director
):
    url = f"/api/v1/quotations/{costed.pk}/costing/"
    for user in (executive, manager, accountant, director):
        answer = as_user(user).get(url)
        assert answer.status_code == 200, user.email
        assert answer.json()["lines"][0]["results"][0]["cost"] == "2476.27"
    # Another Sales Executive does not even see the quotation.
    assert as_user(other_executive).get(url).status_code == 404
    assert as_user(other_executive).put(f"{url}1/", {}, format="json").status_code == 404


def test_a_view_only_sales_user_without_accounting_does_not_see_costing(costed):
    # The Production Planner (a later-phase role) looks at sales but not at accounting.
    Role.objects.filter(code="production_planner").update(is_active=True)
    planner = person("planner@sml.lk", "production_planner", all_divisions=True)
    assert services.visible(planner).filter(pk=costed.pk).exists()
    assert not costing.can_see(planner, costed)
    answer = as_user(planner).get(f"/api/v1/quotations/{costed.pk}/costing/")
    assert answer.status_code == 403


def test_only_the_creator_changes_the_costing_of_a_draft(
    costed, manager, director, accountant, executive, rates, lathe, mill
):
    for user in (manager, director, accountant):
        with pytest.raises(SalesError, match="Only the person who made the quotation"):
            costing.save(user, costed, 1, shaft(rates, lathe, mill))
    url = f"/api/v1/quotations/{costed.pk}/costing/1/"
    assert as_user(manager).put(url, {}, format="json").status_code == 403  # Sales: Enter
    Quotation.objects.filter(pk=costed.pk).update(status=Quotation.Status.SENT)
    costed.refresh_from_db()
    with pytest.raises(SalesError, match="while it is a draft"):
        costing.save(executive, costed, 1, shaft(rates, lathe, mill))


def test_the_creator_saves_and_removes_costing_through_the_api(
    executive, unilever, rates, lathe, mill
):
    q = quotation(executive, unilever)
    client = as_user(executive)
    url = f"/api/v1/quotations/{q.pk}/costing/"
    page = client.get(url).json()
    assert page["can_edit"] is True
    assert page["defaults"] == {
        "overhead_pct": "15.00",
        "margin_pct": "20.00",
        "setup_rate": "1500.00",
    }
    assert [m["code"] for m in page["materials"]] == ["EN8"]
    assert {m["code"] for m in page["machines"]} == {"C-LAT-01", "M-MIL-01"}
    assert page["lines"][0]["costing"] is None
    body = {
        "material": rates.id,
        "size_a_mm": "50",
        "length_mm": "100",
        "cutting_allowance_mm": "5",
        "setup_hours": "2",
        "operations": [
            {"machine": lathe.id, "minutes": "12", "description": "Turn"},
            {"machine": mill.id, "minutes": "6"},
        ],
        "extras": [
            {"description": "Heat treatment", "amount": "85"},
            {"description": "Transport", "amount": "2000", "per_order": True},
        ],
    }
    saved = client.put(f"{url}1/", body, format="json")
    assert saved.status_code == 200, saved.json()
    line = saved.json()["lines"][0]
    assert line["costing"]["weight_kg"] == "1.6184"
    assert [r["suggested_price_lkr"] for r in line["results"]] == ["2971.52", "2419.52"]
    assert AuditEvent.objects.filter(event="quotation_costing_saved").exists()
    wrong = client.put(f"{url}1/", body | {"setup_hours": "abc"}, format="json")
    assert wrong.status_code == 400 and "setup hours" in wrong.json()["detail"]
    removed = client.delete(f"{url}1/")
    assert removed.json()["lines"][0]["costing"] is None


def test_the_quotation_itself_never_carries_costing(costed, executive, manager):
    """What the customer's copy is built from (P15-07) holds no costing figures."""
    for user in (executive, manager):
        detail = as_user(user).get(f"/api/v1/quotations/{costed.pk}/").json()
        assert "costing" not in detail and "results" not in detail
        for line in detail["lines"]:
            assert not {"costing", "results", "cost", "margin"} & set(line)
    listing = as_user(executive).get("/api/v1/quotations/").json()
    assert all("costing" not in row for row in listing)
    assert as_user(executive).get(f"/api/v1/quotations/{costed.pk}/").json()["can_see_costing"]
