"""Routings (backlog P3-03): a machined part's operations by section (machining method) and
machine with standard times, or subcontracted; drafts prepared by the Production Planner and
approved by the Production Manager, never by the preparer; one routing in force per part, the
approved revision never changed; copies and Excel."""

import io

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from openpyxl import load_workbook

from apps.inventory.models import Item
from apps.masters.models import Machine, Section
from apps.production import routings
from apps.production.models import Routing, RoutingOperation
from apps.production.routings import ImportRefused, RoutingError

from .test_access import as_user, person
from .test_vouchers import payee

pytestmark = pytest.mark.django_db
URL = "/api/v1/routings/"


@pytest.fixture
def planner():
    return person("planner@sml.lk", "production_planner", divisions=["WS"])


@pytest.fixture
def manager():
    return person("pm@sml.lk", "production_manager", divisions=["WS", "IM"])


@pytest.fixture
def shaft(planner):
    Machine.objects.create(
        code="M-LAT-01", name="Lathe 1", section=Section.objects.get(code="M-LAT")
    )
    payee("Ceylon Platers", code="S0100")
    return Item.objects.create(
        code="SH-100", name="Drive shaft", category="finished", unit="pcs", created_by=planner
    )


OPERATIONS = [
    {"seq": 10, "name": "Cut to length", "section": "M-BSW", "setup_min": "5", "run_min": "2.5"},
    {"seq": 20, "name": "Turn", "machine": "M-LAT-01", "setup_min": "30", "run_min": "12.25"},
    {
        "seq": 30,
        "name": "Hard chrome plating",
        "subcontract": True,
        "supplier": "S0100",
        "subcontract_cost": "450",
    },
]


def draft(planner, **changed):
    return routings.create(planner, {"item": "SH-100", "operations": OPERATIONS} | changed)


def test_the_planner_prepares_and_the_production_manager_approves(planner, manager, shaft):
    made = as_user(planner).post(
        URL, {"item": "SH-100", "drawing_revision": "B", "operations": OPERATIONS}, format="json"
    )
    assert made.status_code == 201, made.json()
    body = made.json()
    assert (body["revision"], body["status"], body["drawing_revision"]) == (1, "draft", "B")
    assert body["operations"][1]["section"] == "M-LAT"  # taken from the machine
    assert (body["setup_min"], body["run_min"], body["subcontract_cost"]) == (
        "35",
        "14.75",
        "450.00",
    )
    pk = body["id"]
    sent = as_user(planner).post(f"{URL}{pk}/submit/")
    assert sent.json()["status"] == "awaiting" and sent.json()["can_edit"] is False
    # The preparer never approves it.
    assert as_user(planner).post(f"{URL}{pk}/approve/").status_code == 400
    with pytest.raises(RoutingError):
        routings.decide(planner, Routing.objects.get(pk=pk), "approve")
    seen = as_user(manager).get(f"{URL}{pk}/").json()
    assert seen["can_decide"] is True
    done = as_user(manager).post(f"{URL}{pk}/approve/")
    assert done.json()["status"] == "approved"
    assert routings.in_force(shaft).revision == 1


def test_operations_are_checked(planner, shaft):
    for changed, message in [
        ([], "at least one operation"),
        ([{"name": "Turn"}], "give the section"),
        ([{"name": "Turn", "section": "C-XX"}], "no section C-XX"),
        ([{"name": "Turn", "section": "M-MIL", "machine": "M-LAT-01"}], "not in section M-MIL"),
        ([{"name": "Plate", "subcontract": True}], "give the supplier"),
        ([{"name": "Turn", "section": "M-LAT", "run_min": "1.2345"}], "3 decimal places"),
        (
            [
                {"seq": 10, "name": "A", "section": "M-LAT"},
                {"seq": 10, "name": "B", "section": "M-LAT"},
            ],
            "each once",
        ),
        ([{"name": "", "section": "M-LAT"}], "give the operation"),
    ]:
        with pytest.raises(RoutingError, match=message):
            draft(planner, operations=changed)
    draft(planner)
    with pytest.raises(RoutingError, match="already has a routing being prepared"):
        draft(planner)
    supervisor = person("sup@sml.lk", "production_supervisor", divisions=["WS"])
    assert as_user(supervisor).post(URL, {"item": "SH-100"}, format="json").status_code == 400


def test_a_new_revision_replaces_the_one_in_force(planner, manager, shaft):
    first = draft(planner)
    routings.submit(planner, first)
    routings.decide(manager, first, "approve")
    # Approved: never changed or deleted, its operations neither (database).
    with pytest.raises(RoutingError, match="approved"):
        routings.update(planner, Routing.objects.get(pk=first.pk), {"notes": "x"})
    with pytest.raises(DatabaseError), transaction.atomic():
        RoutingOperation.objects.filter(routing=first).update(run_min=1)
    with pytest.raises(DatabaseError), transaction.atomic():
        Routing.objects.filter(pk=first.pk).delete()

    second = routings.copy(planner, Routing.objects.get(pk=first.pk))
    assert (second.revision, second.status, second.operations.count()) == (2, "draft", 3)
    routings.update(
        planner,
        second,
        {"operations": OPERATIONS[:2] + [{"seq": 25, "name": "Grind", "section": "M-GRD"}]},
    )
    routings.submit(planner, second)
    # Sent back with a reason, corrected and sent again.
    routings.decide(manager, Routing.objects.get(pk=second.pk), "send_back", "Add deburring")
    back = routings.payload(Routing.objects.get(pk=second.pk), planner)
    assert (back["status"], back["returned_reason"], back["can_edit"]) == (
        "draft",
        "Add deburring",
        True,
    )
    routings.submit(planner, Routing.objects.get(pk=second.pk))
    routings.decide(manager, Routing.objects.get(pk=second.pk), "approve")
    assert Routing.objects.get(pk=first.pk).status == "obsolete"
    assert routings.in_force(shaft).revision == 2
    assert [o.seq for o in routings.in_force(shaft).operations.all()] == [10, 20, 25]

    # Copied to another part as its first draft.
    Item.objects.create(
        code="SH-200", name="Idler shaft", category="finished", unit="pcs", created_by=planner
    )
    other = as_user(planner).post(f"{URL}{second.pk}/copy/", {"item": "SH-200"}).json()
    assert (other["item"], other["revision"], other["drawing_revision"]) == ("SH-200", 1, "")


def test_drafts_from_excel(planner, manager, shaft):
    first = draft(planner)
    routings.submit(planner, first)
    routings.decide(manager, first, "approve")
    sheet = load_workbook(io.BytesIO(routings.export_workbook())).active
    assert [c.value for c in sheet[1]][:5] == [
        "Item code",
        "Revision",
        "Drawing revision",
        "Op no",
        "Operation",
    ]
    assert sheet.max_row == 4
    sheet["E3"] = "Rough and finish turn"
    sheet.append(["SH-404", "", "", 10, "Turn", "M-LAT"])
    buffer = io.BytesIO()
    sheet.parent.save(buffer)
    with pytest.raises(ImportRefused) as refused:
        routings.import_workbook(planner, buffer.getvalue(), dry_run=True)
    assert refused.value.errors == ["SH-404: There is no item SH-404."]
    sheet.delete_rows(5)
    buffer = io.BytesIO()
    sheet.parent.save(buffer)
    assert routings.import_workbook(planner, buffer.getvalue(), dry_run=True) == {
        "drafts": 1,
        "saved": False,
    }
    assert Routing.objects.count() == 1
    routings.import_workbook(planner, buffer.getvalue(), dry_run=False)
    new = Routing.objects.get(status="draft")
    assert new.revision == 2 and new.operations.get(seq=20).name == "Rough and finish turn"
