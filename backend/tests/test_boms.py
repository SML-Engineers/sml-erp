"""Bills of materials (backlog P3-04): lines of every kind, the machining and moulding
calculators, family moulds, revisions approved by the Production Manager, no item made from
itself at any level, standard cost through the routing and machine rates, copy, compare,
where-used and Excel."""

import io
from datetime import date
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from openpyxl import load_workbook

from apps.inventory.models import Item
from apps.masters.models import Machine, MachineRate, Section
from apps.production import boms, moulds, routings
from apps.production.boms import BomError, ImportRefused
from apps.production.models import Bom, BomLine

from .test_access import as_user, person
from .test_vouchers import payee

pytestmark = pytest.mark.django_db
URL = "/api/v1/boms/"


@pytest.fixture
def planner():
    return person("planner@sml.lk", "production_planner", divisions=["WS", "IM"])


@pytest.fixture
def manager():
    return person("pm@sml.lk", "production_manager", divisions=["WS", "IM"])


def item(user, code, name, category="finished", unit="pcs", **more):
    return Item.objects.create(
        code=code, name=name, category=category, unit=unit, created_by=user, **more
    )


@pytest.fixture
def stock(planner):
    payee("Ceylon Platers", code="S0100")
    return {
        "shaft": item(planner, "SH-100", "Drive shaft"),
        "bar": item(
            planner, "EN8-50", "EN8 bar 50 mm", "raw_material", "kg", standard_kg_per_m=D("15.41")
        ),
        "bearing": item(planner, "BRG-6205", "Bearing 6205", "bought_out"),
        "carton": item(planner, "CTN-S", "Small carton", "packing"),
    }


LINES = [
    {
        "seq": 10,
        "line_type": "raw",
        "component": "EN8-50",
        "stock_size": "Ø50 x 3 m",
        "bar_length_mm": "3000",
        "cut_length_mm": "120",
        "facing_mm": "3",
        "saw_mm": "3",
        "operation_seq": 10,
    },
    {"seq": 20, "line_type": "bought", "component": "BRG-6205", "quantity": "2"},
    {
        "seq": 30,
        "line_type": "Subcontract service",
        "description": "Hard chrome plating",
        "supplier": "S0100",
        "unit_cost": "450",
    },
    {"seq": 40, "line_type": "packing", "component": "CTN-S", "quantity": "0.1"},
]


def shaft_lines(changed=None):
    """The shaft's lines, with changes by line number: shaft_lines({20: {...}})."""
    return [{**line, **(changed or {}).get(line["seq"], {})} for line in LINES]


def test_the_machining_calculator(planner, stock):
    calc = boms.machining(
        stock["bar"],
        bar_length_mm=D("3000"),
        cut_length_mm=D("120"),
        facing_mm=D("3"),
        saw_mm=D("3"),
    )
    assert (calc["length_per_piece_mm"], calc["pieces_per_bar"]) == ("126", 23)
    assert calc["quantity"] == D("1.941660")  # 15.41 kg/m x 0.126 m
    assert calc["blank_weight_kg"] == "1.8954"  # 123 mm
    whole = item(planner, "BAR-50", "Bar 50 mm, 3 m lengths", "raw_material", "pcs")
    assert boms.machining(whole, bar_length_mm=D("3000"), cut_length_mm=D("120"))["quantity"] == (
        D(1) / 25
    ).quantize(D("0.000001"))
    with pytest.raises(BomError, match="longer than the bar"):
        boms.machining(whole, bar_length_mm=D("100"), cut_length_mm=D("120"))
    body = (
        as_user(planner)
        .get(
            f"{URL}machining/?component=EN8-50&bar_length_mm=3000&cut_length_mm=120&facing_mm=3&saw_mm=3"
        )
        .json()
    )
    assert (body["pieces_per_bar"], body["quantity"]) == (23, "1.94166")


def test_a_machined_part_prepared_and_approved(planner, manager, stock):
    made = as_user(planner).post(
        URL,
        {"item": "SH-100", "kind": "machining", "drawing_revision": "B", "lines": shaft_lines()},
        format="json",
    )
    assert made.status_code == 201, made.json()
    body = made.json()
    assert (body["revision"], body["division"], body["status"]) == (1, "WS", "draft")
    lines = {x["seq"]: x for x in body["lines"]}
    assert (lines[10]["quantity"], lines[10]["unit"]) == ("1.94166", "kg")
    assert lines[30]["line_type"] == "subcontract" and lines[30]["quantity"] == "1"
    assert lines[10]["issue_method"] == "manual"
    pk = body["id"]
    as_user(planner).post(f"{URL}{pk}/submit/")
    assert as_user(planner).post(f"{URL}{pk}/approve/").status_code == 400
    back = as_user(manager).post(f"{URL}{pk}/send_back/", {"reason": "Add a spacer"}).json()
    assert (back["status"], back["returned_reason"]) == ("draft", "Add a spacer")
    as_user(planner).post(f"{URL}{pk}/submit/")
    done = as_user(manager).post(f"{URL}{pk}/approve/").json()
    assert done["status"] == "approved"
    bom = Bom.objects.get(pk=pk)
    with pytest.raises(DatabaseError), transaction.atomic():
        BomLine.objects.filter(bom=bom).update(quantity=D("9"))
    with pytest.raises(BomError, match="approved"):
        boms.update(planner, bom, {"notes": "x"})


def test_lines_are_checked(planner, stock):
    for changed, message in [
        ({10: {"component": "NOPE"}}, "no item NOPE"),
        ({20: {"quantity": ""}}, "give the quantity"),
        ({20: {"line_type": "widget"}}, "choose what the line is"),
        ({30: {"supplier": ""}}, "give the supplier"),
        ({30: {"description": ""}}, "describe the service"),
        ({40: {"scrap_pct": "100"}}, "under 100%"),
        ({20: {"component": "SH-100"}}, "cannot be made from itself"),
        ({10: {"bar_length_mm": "100"}}, "longer than the bar"),
    ]:
        with pytest.raises(BomError, match=message):
            boms.create(
                planner, {"item": "SH-100", "kind": "machining", "lines": shaft_lines(changed)}
            )
    boms.create(planner, {"item": "SH-100", "lines": shaft_lines()})
    with pytest.raises(BomError, match="already has a BOM being prepared"):
        boms.create(planner, {"item": "SH-100", "lines": shaft_lines()})


def test_moulding_boms_work_the_resin_out_from_the_mould(planner, manager):
    cap = item(planner, "CAP-28", "Cap 28 mm")
    lid = item(planner, "LID-90", "Lid 90 mm")
    item(planner, "PP-H", "PP homopolymer", "raw_material", "kg")
    item(planner, "MB-BLK", "Black masterbatch", "raw_material", "kg")
    item(planner, "BAG-1K", "Polybag 1000", "packing")
    base = {"cycle_time_s": "12", "shot_weight_g": "40", "runner_weight_g": "4"}
    moulds.create(planner, base | {"code": "MD-001", "name": "Cap", "parts": "CAP-28 x 8"})
    lines = [
        {"line_type": "raw", "component": "PP-H"},
        {"line_type": "masterbatch", "component": "MB-BLK", "pct_of_resin": "2"},
        {"line_type": "packing", "component": "BAG-1K", "quantity": "1"},
    ]
    bom = boms.create(
        planner,
        {
            "item": "CAP-28",
            "kind": "moulding",
            "mould": "MD-001",
            "base_quantity": "1000",
            "reject_pct": "5",
            "max_regrind_pct": "20",
            "outputs": [{"item": "CAP-28", "cavities": 8, "part_weight_g": "4"}],
            "lines": lines,
        },
    )
    body = boms.payload(bom, planner)
    # (8 x 4 g + 4 g runner) x 1.05 = 37.8 g a shot, 4.725 g a cap.
    assert body["resin"] == {
        "shot_g": "37.80",
        "per_piece_g": "4.7250",
        "pieces_per_shot": 8,
        "family": False,
    }
    by = {x["component"]: x for x in body["lines"]}
    assert by["PP-H"]["quantity"] == "4.725"  # kg for 1,000 caps
    assert by["MB-BLK"]["quantity"] == "0.0945"  # 2% of the resin
    assert {x["issue_method"] for x in body["lines"]} == {"backflush"}
    assert body["division"] == "IM"
    with pytest.raises(BomError, match="does not make LID-90"):
        boms.create(
            planner, {"item": "LID-90", "kind": "moulding", "mould": "MD-001", "lines": lines}
        )

    # A family mould: one shot makes 4 caps and 2 lids.
    moulds.create(
        planner,
        base
        | {
            "code": "MD-002",
            "name": "Family",
            "parts": "CAP-28 x 4; LID-90 x 2",
            "runner_weight_g": "6",
        },
    )
    family = boms.create(
        planner,
        {
            "item": "LID-90",
            "kind": "moulding",
            "mould": "MD-002",
            "reject_pct": "2",
            "outputs": [
                {"item": "CAP-28", "cavities": 4, "part_weight_g": "4"},
                {"item": "LID-90", "cavities": 2, "part_weight_g": "10"},
            ],
            "lines": lines[:1],
        },
    )
    shot = boms.payload(family, planner)
    assert shot["resin"]["family"] is True and shot["resin"]["shot_g"] == "42.84"
    assert shot["lines"][0]["quantity"] == "0.04284"  # kg of resin a shot
    assert [o["item"] for o in shot["outputs"]] == ["CAP-28", "LID-90"]
    assert cap and lid


def test_no_item_is_made_from_itself_at_any_level(planner, manager, stock):
    assembly = item(planner, "ASM-1", "Gearbox")
    first = boms.create(
        planner,
        {
            "item": "ASM-1",
            "lines": [{"line_type": "sub_assembly", "component": "SH-100", "quantity": "1"}],
        },
    )
    boms.submit(planner, first)
    boms.decide(manager, first, "approve")
    with pytest.raises(BomError, match="SH-100 would be made from itself: SH-100 > ASM-1 > SH-100"):
        boms.create(
            planner,
            {
                "item": "SH-100",
                "lines": [{"line_type": "sub_assembly", "component": "ASM-1", "quantity": "1"}],
            },
        )
    assert assembly


def test_standard_cost_through_the_levels(planner, manager, stock):
    section = Section.objects.get(code="M-LAT")
    lathe = Machine.objects.create(code="M-LAT-01", name="Lathe 1", section=section)
    MachineRate.objects.create(
        machine=lathe, effective_from=date(2026, 1, 1), rate=D("3000"), created_by=planner
    )
    routing = routings.create(
        planner,
        {
            "item": "SH-100",
            "operations": [{"name": "Turn", "machine": "M-LAT-01", "run_min": "12"}],
        },
    )
    routings.submit(planner, routing)
    routings.decide(manager, routing, "approve")
    bom = boms.create(planner, {"item": "SH-100", "lines": shaft_lines()})
    c = boms.cost(bom)
    assert c["machine"] == D("600.00")  # 12 minutes at LKR 3,000 an hour
    assert c["material"] == D("450.00")  # the plating; no stock bought yet
    assert c["per_unit"] == D("1050.00")
    assert "EN8-50: no stock cost yet" in c["missing"]
    # A customer-supplied bar costs nothing and is not missing.
    free = boms.update(planner, bom, {"lines": shaft_lines({10: {"customer_supplied": True}})})
    assert "EN8-50: no stock cost yet" not in boms.cost(free)["missing"]


def test_copy_compare_where_used_and_excel(planner, manager, stock):
    first = boms.create(planner, {"item": "SH-100", "lines": shaft_lines()})
    boms.submit(planner, first)
    boms.decide(manager, first, "approve")
    second = boms.copy(planner, Bom.objects.get(pk=first.pk))
    assert (second.revision, second.lines.count()) == (2, 4)
    boms.update(planner, second, {"lines": shaft_lines({20: {"quantity": "3"}})})
    diff = as_user(planner).get(f"{URL}compare/?a={first.pk}&b={second.pk}").json()
    changed = [x["component"] for x in diff["lines"] if x["changed"]]
    assert changed == ["BRG-6205"]
    used = as_user(planner).get(f"{URL}where-used/?item=brg-6205").json()
    assert [(b["item"], b["revision"]) for b in used["boms"]] == [("SH-100", 2), ("SH-100", 1)]
    item(planner, "SH-200", "Idler shaft")
    other = as_user(planner).post(f"{URL}{first.pk}/copy/", {"item": "SH-200"}).json()
    assert (other["item"], other["revision"], len(other["lines"])) == ("SH-200", 1, 4)

    sheet = load_workbook(io.BytesIO(boms.export_workbook())).active
    assert [c.value for c in sheet[1]][:6] == [
        "Item code",
        "Kind",
        "Revision",
        "Base quantity",
        "Line no",
        "Line type",
    ]
    # Keep only SH-100's approved revision and change the bearings to 4.
    rows = [
        r for r in sheet.iter_rows(min_row=2, values_only=True) if r[0] == "SH-100" and r[2] == 1
    ]
    book = load_workbook(io.BytesIO(boms.export_workbook()))
    new = book.active
    new.delete_rows(2, new.max_row)
    for r in rows:
        new.append(list(r))
    new["J3"] = 4
    buffer = io.BytesIO()
    book.save(buffer)
    # The part's open draft (revision 2) takes the file's lines.
    assert boms.import_workbook(planner, buffer.getvalue(), dry_run=False) == {
        "drafts": 1,
        "saved": True,
    }
    new["G2"] = "NOPE"
    buffer = io.BytesIO()
    book.save(buffer)
    with pytest.raises(ImportRefused) as refused:
        boms.import_workbook(planner, buffer.getvalue(), dry_run=True)
    assert refused.value.errors == ["SH-100: There is no item NOPE."]
    draft = Bom.objects.get(item__code="SH-100", status="draft")
    assert draft.revision == 2 and draft.lines.get(seq=20).quantity == D("4")
