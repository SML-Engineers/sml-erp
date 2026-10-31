"""Moulding costing and tooling of quotation lines (backlog P15-05, spec 5.1, rule 11)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models import Division
from apps.masters import costing_rates, customers
from apps.masters import services as masters
from apps.masters.models import Section
from apps.sales import costing, services
from apps.sales.costing import CostingInput
from apps.sales.services import BreakInput, LineInput, SalesError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def unilever(executive):
    return customers.create_customer(executive, {"name": "Unilever Sri Lanka"})


def material(accountant, code, kind, rate):
    m = costing_rates.create_material(accountant, {"code": code, "name": code, "kind": kind})
    costing_rates.add_material_rate(accountant, m, effective_from=TODAY, rate=rate)
    return m


@pytest.fixture
def pp(accountant):
    """Polypropylene at LKR 420 per kg; for IM 10% overhead, 25% margin, LKR 1,200 per setup
    hour."""
    costing_rates.add_costing_rate(
        accountant,
        Division.objects.get(code="IM"),
        effective_from=TODAY,
        overhead_pct="10",
        margin_pct="25",
        setup_rate="1200",
    )
    return material(accountant, "PP-H110", "resin", "420")


@pytest.fixture
def white(accountant):
    return material(accountant, "MB-WHITE", "masterbatch", "1800")


@pytest.fixture
def press():
    m = masters.create_machine(
        code="IM-250", section=Section.objects.get(code="IM-MLD"), name="250 t press"
    )
    masters.add_rate(m, effective_from=TODAY, rate="2880")
    return m


def quotation(user, customer, *, price="18.00", breaks=(("50000", "17.50"),), lines=None):
    return services.save(
        user,
        None,
        customer=customer,
        division=Division.objects.get(code="IM"),
        lines=lines
        or [
            LineInput(
                description="Cap, PP, white",
                quantity="10000",
                unit_price=price,
                breaks=[BreakInput(q, p) for q, p in breaks],
            )
        ],
    )


def cap(resin, masterbatch, press, **extra) -> CostingInput:
    """A 10 g cap from a 4-cavity mould with an 8 g runner, 2% white masterbatch, a 20 s
    cycle, 3% rejects, 3 setup hours, cartons of 500 at LKR 120 a carton, and a mould of
    LKR 900,000 spread over 300,000 pieces."""
    return CostingInput(
        **{
            "material": resin,
            "masterbatch": masterbatch,
            "masterbatch_pct": "2",
            "part_weight_g": "10",
            "runner_weight_g": "8",
            "cavities": "4",
            "machine": press,
            "cycle_time_s": "20",
            "reject_pct": "3",
            "setup_hours": "3",
            "packing_amount": "120",
            "packing_per": "carton",
            "pcs_per_carton": "500",
            "tooling": "amortised",
            "tooling_cost": "900000",
            "tooling_qty": "300000",
        }
        | extra
    )


def results(q):
    line = q.lines.get(line_no=1)
    return costing.results(line.costing, line, q.exchange_rate)


@pytest.fixture
def costed(executive, unilever, pp, white, press):
    q = quotation(executive, unilever)
    costing.save(executive, q, 1, cap(pp, white, press))
    return q


# --- Working out the price --------------------------------------------------------------


def test_a_moulded_part_is_costed(costed):
    at_10k, _ = results(costed)
    saved = costed.lines.get().costing
    assert saved.method == "moulding"  # the default for IM
    # 12 g a piece (10 g + 8 g ÷ 4): 0.012 kg × 420 + 2% masterbatch × 1,800 = 5.47
    assert at_10k["material"] == Decimal("5.47")
    # 20 s ÷ 4 cavities = 5 s a piece at LKR 2,880 an hour
    assert at_10k["machining"] == Decimal("4.00")
    assert at_10k["hours_per_1000"] == Decimal("1.39")
    assert at_10k["rejects"] == Decimal("0.28")  # 3% of 9.47
    assert at_10k["setup"] == Decimal("0.36")  # 3 h × 1,200 ÷ 10,000
    assert at_10k["packing"] == Decimal("0.24")  # 120 ÷ 500
    assert at_10k["direct_cost"] == Decimal("10.35")
    assert at_10k["overhead"] == Decimal("1.04")
    assert at_10k["cost"] == Decimal("11.39")
    assert at_10k["margin"] == Decimal("2.85")
    assert at_10k["tooling"] == Decimal("3.00")  # 900,000 ÷ 300,000, no overhead or margin
    assert at_10k["suggested_price_lkr"] == Decimal("17.24")
    assert at_10k["quoted_margin_pct"] == Decimal("31.69")  # (18.00 − 3.00 − 11.39) ÷ 11.39


def test_quantity_breaks_of_a_moulded_part(costed):
    at_50k = results(costed)[1]
    assert at_50k["setup"] == Decimal("0.07")
    assert at_50k["cost"] == Decimal("11.07")
    assert at_50k["suggested_price_lkr"] == Decimal("16.84")
    assert at_50k["quoted_margin_pct"] == Decimal("30.98")


def test_packing_per_piece_and_no_masterbatch(executive, unilever, pp, press):
    q = quotation(executive, unilever)
    saved = costing.save(
        executive,
        q,
        1,
        cap(
            pp,
            None,
            press,
            masterbatch_pct="",
            packing_per="piece",
            packing_amount="0.15",
            tooling="customer",
        ),
    )
    assert saved.masterbatch is None
    at_10k = results(q)[0]
    assert at_10k["material"] == Decimal("5.04")  # 0.012 kg × 420
    assert at_10k["packing"] == Decimal("0.15")
    assert at_10k["tooling"] == Decimal("0.00")  # the customer owns the mould


def test_the_costing_keeps_the_press_and_resin_rates_of_its_date(costed, accountant, pp, press):
    tomorrow = TODAY + timedelta(days=1)
    costing_rates.add_material_rate(accountant, pp, effective_from=tomorrow, rate="999")
    masters.add_rate(press, effective_from=tomorrow, rate="9999")
    saved = costed.lines.get().costing
    assert (saved.material_rate, saved.machine_rate) == (Decimal("420.00"), Decimal("2880.00"))
    assert results(costed)[0]["suggested_price_lkr"] == Decimal("17.24")
    for record in (pp, press):
        record.refresh_from_db()
        assert record.first_used_at is not None


@pytest.mark.parametrize(
    "change, why",
    [
        ({"material": None}, "Choose the resin"),
        ({"part_weight_g": ""}, "part weight"),
        ({"cavities": "1.5"}, "whole number"),
        ({"cavities": "0"}, "more than 0"),
        ({"machine": None}, "moulding machine"),
        ({"cycle_time_s": ""}, "cycle time"),
        ({"reject_pct": "100"}, "below 100"),
        ({"masterbatch_pct": ""}, "masterbatch %"),
        ({"pcs_per_carton": ""}, "pieces go in a carton"),
        ({"tooling_qty": ""}, "spread"),
        ({"tooling": "rental"}, "how the tooling is charged"),
    ],
)
def test_wrong_moulding_costing_is_refused(executive, unilever, pp, white, press, change, why):
    q = quotation(executive, unilever)
    with pytest.raises(SalesError, match=why):
        costing.save(executive, q, 1, cap(pp, white, press, **change))


def test_the_resin_and_masterbatch_must_be_the_right_kind(executive, unilever, pp, white, press):
    q = quotation(executive, unilever)
    with pytest.raises(SalesError, match="is a masterbatch: choose the resin"):
        costing.save(executive, q, 1, cap(white, white, press))
    with pytest.raises(SalesError, match="is not a masterbatch"):
        costing.save(executive, q, 1, cap(pp, pp, press))


def test_a_workshop_machine_cannot_mould(executive, unilever, pp, white):
    lathe = masters.create_machine(
        code="C-LAT-01", section=Section.objects.get(code="C-LAT"), name="Lathe"
    )
    q = quotation(executive, unilever)
    with pytest.raises(SalesError, match="not a working machine of IM"):
        costing.save(executive, q, 1, cap(pp, white, lathe))


def test_switching_a_line_to_machining_clears_the_moulding_figures(
    executive, unilever, pp, white, press, costed
):
    saved = costing.save(executive, costed, 1, CostingInput(method="machining", setup_hours="1"))
    assert saved.method == "machining"
    assert (saved.machine, saved.part_weight_g, saved.cavities) == (None, None, None)
    assert results(costed)[0]["hours_per_1000"] is None


# --- Tooling lines ----------------------------------------------------------------------


def test_a_tooling_line_is_charged_once(executive, unilever, pp, white, press):
    q = quotation(
        executive,
        unilever,
        lines=[
            LineInput(description="Cap, PP, white", quantity="10000", unit_price="15.00"),
            LineInput(
                description="Injection mould, 4 cavities",
                quantity="1",
                unit_price="950000",
                is_tooling=True,
            ),
        ],
    )
    part, mould = q.lines.order_by("line_no")
    assert (part.is_tooling, mould.is_tooling) == (False, True)
    assert q.subtotal == Decimal("1100000.00")
    saved = costing.save(executive, q, 1, cap(pp, white, press, tooling="separate", tooling_qty=""))
    assert saved.tooling == "separate" and saved.tooling_cost == Decimal("900000.00")
    assert results(q)[0]["tooling"] == Decimal("0.00")  # charged on the mould's own line


def test_the_api_costs_a_moulded_line(executive, unilever, pp, white, press):
    q = quotation(executive, unilever)
    client = as_user(executive)
    url = f"/api/v1/quotations/{q.pk}/costing/"
    page = client.get(url).json()
    assert page["default_method"] == "moulding"
    assert {m["kind"] for m in page["materials"]} == {"resin", "masterbatch"}
    assert [m["code"] for m in page["machines"]] == ["IM-250"]
    body = {
        "method": "moulding",
        "material": pp.id,
        "masterbatch": white.id,
        "masterbatch_pct": "2",
        "part_weight_g": "10",
        "runner_weight_g": "8",
        "cavities": "4",
        "machine": press.id,
        "cycle_time_s": "20",
        "reject_pct": "3",
        "setup_hours": "3",
        "packing_amount": "120",
        "packing_per": "carton",
        "pcs_per_carton": "500",
        "tooling": "amortised",
        "tooling_cost": "900000",
        "tooling_qty": "300000",
    }
    saved = client.put(f"{url}1/", body, format="json")
    assert saved.status_code == 200, saved.json()
    line = saved.json()["lines"][0]
    assert line["costing"]["machine"]["code"] == "IM-250"
    assert line["costing"]["cavities"] == 4
    assert [r["suggested_price_lkr"] for r in line["results"]] == ["17.24", "16.84"]
    detail = client.get(f"/api/v1/quotations/{q.pk}/").json()
    assert detail["lines"][0]["is_tooling"] is False
    assert not {"costing", "results"} & set(detail["lines"][0])
