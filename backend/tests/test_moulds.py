"""Moulds (backlog P3-01): parts and cavities, size and the machines a mould fits, company
or customer ownership, the fixed asset link, Excel export and import, QR labels; the code
fixed and the mould never deleted once used."""

import io
from datetime import date
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone
from openpyxl import load_workbook

from apps.assets import services as assets
from apps.assets.models import AssetClass
from apps.core.models import Division
from apps.inventory.models import Item
from apps.masters import customers
from apps.masters.models import Machine, Section
from apps.production import moulds
from apps.production.models import Mould
from apps.production.moulds import ImportRefused, MouldError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db
URL = "/api/v1/moulds/"


@pytest.fixture
def planner():
    return person("planner@sml.lk", "production_planner", divisions=["IM"])


@pytest.fixture
def parts(planner):
    return [
        Item.objects.create(
            code=code, name=name, category="finished", unit="pcs", created_by=planner
        )
        for code, name in [("CAP-28", "Bottle cap 28 mm"), ("LID-90", "Lid 90 mm")]
    ]


@pytest.fixture
def machines():
    section = Section.objects.get(code="IM-MLD")
    big = Machine.objects.create(
        code="IMM-250",
        name="Haitian 250 t",
        section=section,
        clamping_force_t=D("250"),
        max_shot_weight_g=D("600"),
        tie_bar_h_mm=D("570"),
        tie_bar_v_mm=D("570"),
        max_mould_thickness_mm=D("550"),
    )
    small = Machine.objects.create(
        code="IMM-90",
        name="Haitian 90 t",
        section=section,
        clamping_force_t=D("90"),
        max_shot_weight_g=D("150"),
        tie_bar_h_mm=D("360"),
        tie_bar_v_mm=D("360"),
    )
    return big, small


def values(**changed):
    return {
        "code": "MD-001",
        "name": "Cap 28 mm, 8 cavities",
        "parts": [{"item": "CAP-28", "cavities": 8}],
        "cycle_time_s": "12.5",
        "shot_weight_g": "36.0",
        "runner_weight_g": "4.0",
        "tonnage_t": "120",
        "width_mm": "400",
        "height_mm": "450",
        "thickness_mm": "380",
        "machines": ["IMM-250", "IMM-90"],
        "pm_interval_shots": "50000",
    } | changed


def test_a_mould_its_parts_and_the_machines_it_fits(planner, parts, machines):
    made = as_user(planner).post(URL, values(), format="json")
    assert made.status_code == 201, made.json()
    body = made.json()
    assert body["division"] == "IM" and body["owner"] == "company"
    assert body["parts"] == [{"item": "CAP-28", "name": "Bottle cap 28 mm", "cavities": 8}]
    assert body["pm_due_at"] == 50000
    # Too big for the 90 t machine: a warning, never a refusal.
    assert body["warnings"] == [
        "IMM-90: Clamping force: the mould needs 120 t, IMM-90 has 90",
        "IMM-90: Tie bars: the mould is 400 x 450 mm, IMM-90 has 360 x 360 mm between its tie bars",
    ]
    fit = as_user(planner).get(f"{URL}{body['id']}/fit/?machine=imm-250").json()
    assert fit == {"machine": "IMM-250", "warnings": []}
    # Turned round, the mould still passes between the tie bars.
    mould = Mould.objects.get()
    mould.width_mm, mould.height_mm = D("560"), D("300")
    assert moulds.fit(mould, machines[0]) == []

    family = as_user(planner).patch(
        f"{URL}{body['id']}/",
        {"parts": "CAP-28 x 4; LID-90 x 2", "machines": ["IMM-250"]},
        format="json",
    )
    assert [(p["item"], p["cavities"]) for p in family.json()["parts"]] == [
        ("CAP-28", 4),
        ("LID-90", 2),
    ]
    assert family.json()["warnings"] == []


def test_the_values_are_checked(planner, parts, machines):
    for changed, message in [
        ({"code": "md 1"}, "capital letters"),
        ({"parts": []}, "Give the part"),
        ({"parts": [{"item": "NOPE", "cavities": 2}]}, "no item NOPE"),
        ({"parts": [{"item": "CAP-28", "cavities": 0}]}, "1 to 512"),
        ({"cycle_time_s": "0"}, "more than 0 seconds"),
        ({"cycle_time_s": "12.555"}, "at most 2 decimal"),
        ({"runner_weight_g": "40"}, "runner weighs less"),
        ({"machines": ["X-1"]}, "no machine X-1"),
        ({"owner": "customer"}, "Give the customer"),
    ]:
        with pytest.raises(MouldError, match=message):
            moulds.create(planner, values(**changed))
    moulds.create(planner, values())
    with pytest.raises(MouldError, match="already a mould MD-001"):
        moulds.create(planner, values())
    supervisor = person("sup@sml.lk", "production_supervisor", divisions=["IM"])
    assert as_user(supervisor).post(URL, values(code="MD-002"), format="json").status_code == 403


def test_customer_moulds_and_the_fixed_asset(planner, parts, machines):
    sales = person("sales@sml.lk", "sales_executive", all_divisions=True)
    buyer = customers.create_customer(sales, {"name": "Lanka Bottlers"}, confirmed=True)
    owned = moulds.create(planner, values(code="MD-010", owner="customer", customer=buyer.code))
    assert owned.customer == buyer and owned.asset is None
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    moulds_class = AssetClass.objects.get(code="MOULDS")
    assets.add_rate(
        accountant, moulds_class, effective_from=date(2026, 4, 1), method="straight_line",
        rate="20",
    )  # fmt: skip
    asset = assets.register(
        accountant,
        asset_class=moulds_class,
        division=Division.objects.get(code="IM"),
        name="Cap mould",
        acquisition_date=date(2026, 4, 1),
        cost="850000.00",
    )
    with pytest.raises(MouldError, match="not the company's fixed asset"):
        moulds.update(planner, owned, {"asset": asset.code})
    mine = moulds.create(planner, values(asset=asset.code))
    assert mine.asset == asset
    with pytest.raises(MouldError, match=f"already mould {mine.code}"):
        moulds.create(planner, values(code="MD-011", asset=asset.code))
    # The database holds the rule too.
    with pytest.raises(DatabaseError), transaction.atomic():
        Mould.objects.filter(pk=owned.pk).update(customer=None)


def test_a_used_mould_keeps_its_code_and_is_retired_not_deleted(planner, parts, machines):
    unused = moulds.create(planner, values(code="MD-020"))
    moulds.delete(planner, unused)
    used = moulds.create(planner, values())
    Mould.objects.filter(pk=used.pk).update(first_used_at=timezone.now())
    used.refresh_from_db()
    with pytest.raises(MouldError, match="its code cannot change"):
        moulds.update(planner, used, {"code": "MD-099"})
    with pytest.raises(MouldError, match="retire it instead"):
        moulds.delete(planner, used)
    with pytest.raises(DatabaseError), transaction.atomic():
        Mould.objects.filter(pk=used.pk).delete()
    retired = as_user(planner).patch(f"{URL}{used.pk}/", {"status": "Retired"}, format="json")
    assert retired.json()["status"] == "retired"


def test_excel_export_import_and_labels(planner, parts, machines):
    moulds.create(planner, values())
    exported = as_user(planner).get(f"{URL}export/")
    sheet = load_workbook(io.BytesIO(exported.content)).active
    head = [c.value for c in sheet[1]]
    row = dict(zip(head, [c.value for c in sheet[2]], strict=True))
    assert row["Parts (code x cavities; ...)"] == "CAP-28 x 8"
    assert row["Compatible machines (codes; ...)"] == "IMM-250; IMM-90"
    # Change one mould and add another in the same file.
    sheet["B2"] = "Cap 28 mm, 8 cav."
    sheet.append(["MD-002", "Lid 90 mm", "IM", "LID-90 x 2", "Company", "", "", 18, 80, 6])
    sheet.append(["MD-003", "Broken", "IM", "NOPE x 2", "Company", "", "", 18, 80, 6])
    buffer = io.BytesIO()
    sheet.parent.save(buffer)
    with pytest.raises(ImportRefused) as refused:
        moulds.import_workbook(planner, buffer.getvalue(), dry_run=True)
    assert refused.value.errors == ["Row 4 (MD-003): There is no item NOPE."]
    sheet.delete_rows(4)
    buffer = io.BytesIO()
    sheet.parent.save(buffer)
    assert moulds.import_workbook(planner, buffer.getvalue(), dry_run=True) == {
        "created": 1,
        "changed": 1,
        "saved": False,
    }
    assert not Mould.objects.filter(code="MD-002").exists()
    moulds.import_workbook(planner, buffer.getvalue(), dry_run=False)
    assert Mould.objects.get(code="MD-001").name == "Cap 28 mm, 8 cav."
    assert Mould.objects.get(code="MD-002").parts.get().cavities == 2
    labels = as_user(planner).get(f"{URL}labels/")
    assert labels.status_code == 200 and labels.content.startswith(b"%PDF")
