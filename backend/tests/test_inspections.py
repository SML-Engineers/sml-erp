"""Incoming inspection and QC acceptance (backlog P16-08, spec 6A.3, 6A.4)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.models import Division, Notification
from apps.inventory import inspections, items, receipts
from apps.inventory.inspections import InspectionError, ParameterInput, ResultInput
from apps.inventory.models import IncomingInspection, InspectionResult
from apps.inventory.packages import PackageInput
from apps.inventory.receipts import ReceiptError
from apps.masters.models import Currency, Supplier
from apps.purchasing import orders
from apps.purchasing.orders import LineInput as POLine

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
PDF = b"%PDF-1.4\n" + b"0" * 64
D = IncomingInspection.Decision
St = IncomingInspection.Status


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def buyer():
    return person("buyer@sml.lk", "purchasing_officer", all_divisions=True)


@pytest.fixture
def stores():
    return person("stores@sml.lk", "store_supervisor", divisions=("IM",))


@pytest.fixture
def qc():
    return person("qc@sml.lk", "qc_inspector", divisions=("IM",))


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def resin(buyer):
    return items.create_item(
        buyer,
        {
            "code": "PP-H-WHITE",
            "name": "PP homopolymer",
            "category": "raw_material",
            "unit": "kg",
            "package_type": "bag",
            "package_tare": "0.1",
        },
    )


@pytest.fixture
def plan(qc, resin):
    return inspections.save_plan(
        qc,
        None,
        {"name": "PP resin", "item": resin, "sampling": "fixed", "sample_value": "2"},
        [
            ParameterInput("Melt flow index", "number", "10", "14", "g/10 min", critical=True),
            ParameterInput("Bag condition", "pass_fail"),
        ],
    )


def receive(buyer, director, stores, item, bags=4, damaged=0):
    supplier = Supplier.objects.create(
        code=f"S{Supplier.objects.count() + 1:04d}",
        name="SDD Polymer",
        currency=Currency.objects.get(code="LKR"),
    )
    order = orders.create(
        buyer,
        supplier=supplier,
        division=Division.objects.get(code="IM"),
        delivery_date=TODAY + timedelta(days=7),
        lines=[POLine(item, "100", "420")],
    )
    orders.submit(buyer, order)
    orders.approve(director, order)
    grn = receipts.create(stores, order)
    receipts.set_packages(
        stores,
        grn,
        1,
        [PackageInput(gross_weight="25.1", damaged=n < damaged) for n in range(bags)],
    )
    return receipts.confirm(stores, grn).lines.get()


@pytest.fixture
def line(buyer, director, stores, resin, plan):
    return receive(buyer, director, stores, resin)


def results(mfi="12", bag=True):
    return [ResultInput(1, value=mfi), ResultInput(2, passed=bag)]


# --- Plans -----------------------------------------------------------------------------------


def test_the_qc_inspector_sets_up_plans(plan, qc, resin, buyer):
    assert [(p.name, p.kind, p.critical) for p in plan.parameters.all()] == [
        ("Melt flow index", "number", True),
        ("Bag condition", "pass_fail", False),
    ]
    assert inspections.plan_for(resin) == plan
    category = inspections.save_plan(
        qc, None, {"name": "Raw materials", "category": "raw_material", "sampling": "all"}, []
    )
    other = items.create_item(buyer, {"code": "ABS-1", "name": "ABS", "category": "raw_material"})
    assert inspections.plan_for(other) == category
    with pytest.raises(InspectionError, match="already has an active plan"):
        inspections.save_plan(qc, None, {"name": "Again", "item": resin, "sampling": "all"}, [])
    with pytest.raises(InspectionError, match="Only the QC Inspector"):
        inspections.save_plan(
            buyer, None, {"name": "X", "category": "spare", "sampling": "all"}, []
        )


@pytest.mark.parametrize(
    "values, parameters, why",
    [
        ({"name": "", "category": "spare", "sampling": "all"}, [], "name"),
        ({"name": "X", "sampling": "all"}, [], "one item or for one category"),
        (
            {"name": "X", "category": "spare", "sampling": "percent", "sample_value": "150"},
            [],
            "at most 100",
        ),
        (
            {"name": "X", "category": "spare", "sampling": "fixed", "sample_value": "2.5"},
            [],
            "whole number",
        ),
        (
            {"name": "X", "category": "spare", "sampling": "all"},
            [ParameterInput("MFI", "number")],
            "minimum, the maximum",
        ),
        (
            {"name": "X", "category": "spare", "sampling": "all"},
            [ParameterInput("MFI", "number", "5", "1")],
            "more than the maximum",
        ),
    ],
)
def test_wrong_plans_are_refused(qc, values, parameters, why):
    with pytest.raises(InspectionError, match=why):
        inspections.save_plan(qc, None, values, parameters)


# --- Inspecting -------------------------------------------------------------------------------


def test_a_confirmed_grn_line_waits_for_qc_with_the_plan_copied(line, qc, plan):
    assert list(inspections.queue(qc)) == [line]
    inspection = inspections.start(qc, line)
    assert (inspection.plan, inspection.sample_size, inspection.accepted_quantity) == (
        plan,
        2,
        Decimal("100.000"),
    )
    assert [(r.name, r.minimum, r.maximum) for r in inspection.results.all()] == [
        ("Melt flow index", Decimal("10"), Decimal("14")),
        ("Bag condition", None, None),
    ]
    # A later change to the plan does not change this inspection (rule 11).
    inspections.save_plan(qc, plan, {"name": "PP resin"}, [ParameterInput("Colour", "pass_fail")])
    assert inspection.results.count() == 2


def test_the_person_who_received_cannot_inspect(buyer, director, resin, plan):
    both = person("both@sml.lk", "store_supervisor", "qc_inspector", divisions=("IM",))
    line = receive(buyer, director, both, resin)
    with pytest.raises(InspectionError, match="segregation of duties"):
        inspections.start(both, line)
    with pytest.raises(InspectionError, match="Only the QC Inspector"):
        inspections.start(director, line)


def test_qc_accepts_all_but_two_wet_bags(line, qc):
    inspection = inspections.start(qc, line)
    inspection = inspections.save(qc, inspection, results=results(), rejected_packages=[2, 4])
    assert (inspection.accepted_quantity, inspection.rejected_quantity) == (
        Decimal("50.000"),
        Decimal("50.000"),
    )
    assert [r.within_limits for r in inspection.results.all()] == [True, True]
    inspection = inspections.decide(qc, inspection, D.ACCEPTED)
    assert (inspection.status, inspection.decision, inspection.inspector) == (
        St.DECIDED,
        D.ACCEPTED,
        qc,
    )
    assert [r.package.package_no for r in inspection.rejected_packages.all()] == [2, 4]
    assert not inspections.queue(qc).exists()
    line.refresh_from_db()
    assert line.received_quantity == Decimal("100.000")  # QC never changes what was received


def test_damaged_bags_are_already_set_aside(buyer, director, stores, qc, resin, plan):
    line = receive(buyer, director, stores, resin, damaged=1)
    inspection = inspections.start(qc, line)
    assert inspection.accepted_quantity == Decimal("75.000")
    with pytest.raises(InspectionError, match="received damaged"):
        inspections.save(qc, inspection, results=[], rejected_packages=[1])


def test_every_check_is_entered_before_accepting(line, qc):
    inspection = inspections.start(qc, line)
    inspections.save(qc, inspection, results=[ResultInput(1, value="12")])
    with pytest.raises(InspectionError, match="Bag condition"):
        inspections.decide(qc, inspection, D.ACCEPTED)


def test_a_failed_critical_check_cannot_simply_be_accepted(line, qc, director):
    inspection = inspections.start(qc, line)
    inspection = inspections.save(qc, inspection, results=results(mfi="15.5"))
    assert inspection.results.get(position=1).within_limits is False
    with pytest.raises(InspectionError, match="critical check failed .Melt flow index."):
        inspections.decide(qc, inspection, D.ACCEPTED)
    with pytest.raises(InspectionError, match="reason"):
        inspections.decide(qc, inspection, D.DEVIATION)
    inspection = inspections.decide(qc, inspection, D.DEVIATION, "MFI slightly high; trial OK")
    assert inspection.status == St.DEVIATION_REQUESTED
    assert Notification.objects.filter(user=director, event="approval_waiting").exists()
    with pytest.raises(InspectionError):
        inspections.approve_deviation(qc, inspection)  # never the inspector
    inspection = inspections.approve_deviation(director, inspection, "Use for black parts")
    assert (inspection.status, inspection.decision) == (St.DECIDED, D.DEVIATION)


def test_a_deviation_needs_a_failed_check(line, qc):
    inspection = inspections.start(qc, line)
    inspections.save(qc, inspection, results=results())
    with pytest.raises(InspectionError, match="No check failed"):
        inspections.decide(qc, inspection, D.DEVIATION, "Just in case")


def test_a_failed_minor_check_can_be_accepted(line, qc):
    inspection = inspections.start(qc, line)
    inspections.save(qc, inspection, results=results(bag=False), notes="Two bags dusty")
    assert inspections.decide(qc, inspection, D.ACCEPTED).decision == D.ACCEPTED


def test_the_director_sends_a_deviation_back_and_qc_rejects(line, qc, director):
    inspection = inspections.start(qc, line)
    inspections.save(qc, inspection, results=results(mfi="20"))
    inspections.decide(qc, inspection, D.DEVIATION, "Customer may accept")
    inspection = inspections.send_back(director, inspection, "Return it to the supplier")
    assert inspection.status == St.DRAFT
    with pytest.raises(InspectionError, match="reason"):
        inspections.decide(qc, inspection, D.REJECTED)
    inspection = inspections.decide(qc, inspection, D.REJECTED, "MFI 20, outside 10 to 14")
    assert (inspection.accepted_quantity, inspection.rejected_quantity) == (0, Decimal("100.000"))


def test_a_decided_inspection_never_changes(line, qc):
    inspection = inspections.start(qc, line)
    inspections.save(qc, inspection, results=results())
    inspection = inspections.decide(qc, inspection, D.ACCEPTED)
    with pytest.raises(InspectionError):
        inspections.save(qc, inspection, results=results(mfi="1"))
    with pytest.raises(DatabaseError, match="cannot be changed"), transaction.atomic():
        IncomingInspection.objects.filter(pk=inspection.pk).update(accepted_quantity=Decimal("1"))
    with pytest.raises(DatabaseError, match="cannot change"), transaction.atomic():
        InspectionResult.objects.filter(inspection=inspection).update(value=Decimal("1"))
    with pytest.raises(DatabaseError, match="cannot"), transaction.atomic():
        IncomingInspection.objects.filter(pk=inspection.pk).delete()


def test_an_item_without_packages_accepts_part_of_the_quantity(buyer, director, stores, qc):
    inserts = items.create_item(
        buyer, {"code": "M6-INSERT", "name": "Insert", "category": "bought_out", "unit": "pcs"}
    )
    supplier = Supplier.objects.create(
        code="S0009", name="Fasteners", currency=Currency.objects.get(code="LKR")
    )
    order = orders.create(
        buyer,
        supplier=supplier,
        division=Division.objects.get(code="IM"),
        delivery_date=TODAY + timedelta(days=7),
        lines=[POLine(inserts, "1000", "12")],
    )
    orders.submit(buyer, order)
    orders.approve(director, order)
    line = receipts.confirm(stores, receipts.create(stores, order)).lines.get()
    inspection = inspections.start(qc, line)  # no plan: nothing to enter
    with pytest.raises(InspectionError, match="between 0 and"):
        inspections.save(qc, inspection, results=[], accepted_quantity="1001")
    inspection = inspections.save(qc, inspection, results=[], accepted_quantity="980")
    assert inspection.rejected_quantity == 20
    assert inspections.decide(qc, inspection, D.ACCEPTED).status == St.DECIDED


def test_an_item_needing_no_inspection_is_accepted_on_confirming(buyer, director, stores, qc):
    grease = items.create_item(
        buyer,
        {
            "code": "GREASE",
            "name": "Grease",
            "category": "consumable",
            "unit": "kg",
            "inspection_required": False,
        },
    )
    supplier = Supplier.objects.create(
        code="S0008", name="Lubes", currency=Currency.objects.get(code="LKR")
    )
    order = orders.create(
        buyer,
        supplier=supplier,
        division=Division.objects.get(code="IM"),
        delivery_date=TODAY + timedelta(days=7),
        lines=[POLine(grease, "5", "900")],
    )
    orders.submit(buyer, order)
    orders.approve(director, order)
    line = receipts.confirm(stores, receipts.create(stores, order)).lines.get()
    assert (line.inspection.automatic, line.inspection.accepted_quantity) == (True, 5)
    assert not inspections.queue(qc).exists()
    receipts.request_reversal(stores, line.receipt, "Wrong PO")  # still allowed


def test_a_grn_qc_has_started_on_cannot_be_reversed(line, qc, stores):
    inspections.start(qc, line)
    with pytest.raises(ReceiptError, match="QC has started"):
        receipts.request_reversal(stores, line.receipt, "Wrong PO")


def test_certificates_are_attached(line, qc):
    inspection = inspections.start(qc, line)
    attachment = inspections.add_attachment(qc, inspection, SimpleUploadedFile("coa.pdf", PDF))
    assert attachment.content_type == "application/pdf"
    with pytest.raises(InspectionError, match="JPG, PNG and PDF"):
        inspections.add_attachment(qc, inspection, SimpleUploadedFile("x.pdf", b"nope"))


# --- Through the API ---------------------------------------------------------------------------


def test_the_api_inspects_and_the_director_approves(line, qc, director, stores):
    client = as_user(qc)
    queue = client.get("/api/v1/inspections/queue/").json()
    assert queue["can_inspect"] and [row["line"] for row in queue["lines"]] == [line.pk]
    started = client.post("/api/v1/inspections/", {"line": line.pk}, format="json")
    assert started.status_code == 201, started.json()
    pk = started.json()["id"]
    saved = client.put(
        f"/api/v1/inspections/{pk}/",
        {
            "results": [{"position": 1, "value": "16"}, {"position": 2, "passed": True}],
            "rejected_packages": [3],
            "notes": "MFI high",
        },
        format="json",
    )
    assert saved.status_code == 200, saved.json()
    body = saved.json()
    assert body["accepted_quantity"] == "75.000"
    assert [r["within_limits"] for r in body["results"]] == [False, True]
    assert [p["rejected"] for p in body["packages"]] == [False, False, True, False]
    refused = client.post(
        f"/api/v1/inspections/{pk}/decide/", {"decision": "accepted"}, format="json"
    )
    assert refused.status_code == 400 and "critical" in refused.json()["detail"]
    asked = client.post(
        f"/api/v1/inspections/{pk}/decide/",
        {"decision": "deviation", "reason": "Trial passed"},
        format="json",
    )
    assert asked.json()["status"] == "deviation_requested"
    boss = as_user(director)
    assert [row["id"] for row in boss.get("/api/v1/inspections/?waiting=me").json()] == [pk]
    approved = boss.post(f"/api/v1/inspections/{pk}/approve/", {}, format="json")
    assert approved.json()["decision"] == "deviation"
    grn = as_user(stores).get(f"/api/v1/goods-receipts/{line.receipt_id}/").json()
    assert grn["lines"][0]["inspection"]["decision"] == "deviation"


def test_the_api_saves_plans(qc, resin):
    client = as_user(qc)
    made = client.post(
        "/api/v1/inspection-plans/",
        {
            "name": "Steel bars",
            "category": "raw_material",
            "sampling": "percent",
            "sample_value": "10",
            "parameters": [
                {
                    "name": "Diameter",
                    "kind": "number",
                    "minimum": "39.8",
                    "maximum": "40.2",
                    "unit": "mm",
                },
                {"name": "Heat no. matches certificate", "kind": "pass_fail", "critical": True},
            ],
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    listed = client.get("/api/v1/inspection-plans/").json()
    assert listed["can_edit"] and [p["name"] for p in listed["plans"]] == ["Steel bars"]


def test_people_without_quality_access_see_nothing(line):
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get("/api/v1/inspections/queue/").status_code == 403
