"""Subcontract operations (backlog P3-13): parts sent out to the supplier of a subcontract
operation on a numbered note, never more than the operation has received; counted back as
good and rejected, never more than is out (service and database); good parts go on to the
next operation; and the supplier's bill coded to the job on voucher lines and supplier
invoice lines."""

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError

from apps.core.models import Division
from apps.production import jobs, subcontract
from apps.production.links import OrderNotFound, order_for
from apps.production.models import SubcontractDispatch, SubcontractReturn
from apps.production.subcontract import SubcontractError
from apps.purchasing import invoices
from apps.purchasing.invoices import InvoiceError, LineInput
from apps.vouchers import services
from apps.vouchers.services import CodingInput, VoucherError

from .test_access import as_user, person
from .test_job_cards import job, line, open_report, save, steps, supervisor  # noqa: F401
from .test_job_orders import accountant, manager, planner, shaft, shafts  # noqa: F401
from .test_shift_reports import clock  # noqa: F401
from .test_supplier_invoices import (  # noqa: F401
    buyer,
    director,
    grn_line,
    inserts,
    memory_storage,
    stores,
    supplier,
)
from .test_vouchers import attach, draft

pytestmark = pytest.mark.django_db


@pytest.fixture
def turned(clock, supervisor, job):  # noqa: F811
    """18 shafts cut, 15 turned (2 rejected): 15 ready for hard chrome plating (op 30)."""
    save(supervisor, open_report(supervisor, "M-BSW"), line(job, 10, completed="18"))
    save(
        supervisor,
        open_report(supervisor, "M-LAT"),
        line(job, 20, completed="15", rejects=[{"reason": "SURFACE", "quantity": "2"}]),
    )
    return job


def send(user, job, **more):  # noqa: F811
    return subcontract.send_out(user, job, {"operation": "30", "quantity": "10"} | more)


def back(user, dispatch, **more):
    return subcontract.receive_back(user, dispatch.job, {"dispatch": dispatch.pk} | more)


def test_parts_go_out_to_the_supplier_and_come_back_counted(planner, turned):  # noqa: F811
    job = turned  # noqa: F811
    with pytest.raises(SubcontractError, match="is done in the workshop"):
        send(planner, job, operation="20")
    with pytest.raises(SubcontractError, match="has 15 pieces ready to send"):
        send(planner, job, quantity="16")
    made = as_user(planner).post(
        f"/api/v1/job-orders/{job.pk}/send-out/",
        {"operation": "30", "quantity": "10", "notes": "Hard chrome 25 micron"},
        format="json",
    )
    assert made.status_code == 201, made.json()
    body = made.json()
    assert body["dispatch"]["number"].startswith("SC")
    [sent] = body["subcontract"]
    assert (sent["supplier"], sent["quantity"], sent["out"]) == ("S0100", "10", "10")
    flow = steps(job)
    assert (flow[30]["received"], flow[30]["in_hand"], flow[30]["at_supplier"]) == ("15", "5", "10")
    with pytest.raises(SubcontractError, match="has 5 pieces ready to send"):
        send(planner, job, quantity="6")
    dispatch = SubcontractDispatch.objects.get(job=job)
    # Counted back: 8 good, 1 rejected by our check.
    with pytest.raises(SubcontractError, match="reason"):
        back(planner, dispatch, good="8", rejected="1")
    with pytest.raises(SubcontractError, match="Count the pieces"):
        back(planner, dispatch)
    back(planner, dispatch, good="8", rejected="1", reason="Pitting on the chrome")
    with pytest.raises(SubcontractError, match=r"has 1 pieces still at the supplier; 2 counted"):
        back(planner, dispatch, good="2")
    flow = steps(job)
    assert (flow[30]["completed"], flow[30]["rejected"], flow[30]["at_supplier"]) == ("8", "1", "1")
    assert flow[30]["finished"] == "8"  # the last operation: 8 shafts finished
    # The note that goes with the parts.
    note = as_user(planner).get(f"/api/v1/job-orders/sent/{dispatch.pk}/note/")
    assert note.status_code == 200 and note.content.startswith(b"%PDF")


def test_only_the_planner_or_stores_and_never_changed(planner, turned):  # noqa: F811
    job = turned  # noqa: F811
    clerk = person("clerk2@sml.lk", "clerk", all_divisions=True)
    with pytest.raises(SubcontractError, match="Production Planner or the stores person"):
        send(clerk, job)
    dispatch = send(planner, job)
    back(planner, dispatch, good="4")
    with pytest.raises(DatabaseError, match="never changed or deleted"), transaction.atomic():
        SubcontractDispatch.objects.filter(pk=dispatch.pk).update(quantity=20)
    with pytest.raises(DatabaseError, match="never changed or deleted"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM production_subcontractreturn")
    with pytest.raises(DatabaseError, match="More is received back"), transaction.atomic():
        SubcontractReturn.objects.create(
            dispatch=dispatch, received_on=dispatch.sent_on, good=7, created_by=planner
        )
    jobs.complete(planner, job)
    with pytest.raises(SubcontractError, match="completed"):
        back(planner, dispatch, good="1")


def test_the_suppliers_bill_is_coded_to_the_job(
    planner,  # noqa: F811
    accountant,  # noqa: F811
    job,  # noqa: F811
    supplier,  # noqa: F811
    grn_line,  # noqa: F811
):
    clerk = person("clerk3@sml.lk", "clerk", all_divisions=True)
    voucher = draft(clerk, supplier)
    attach(clerk, voucher)
    services.submit(clerk, voucher)
    with pytest.raises(VoucherError, match="Line 1: There is no job order or production order JO1"):
        services.code_lines(accountant, voucher, [CodingInput(1, job_ref="JO1")])
    draft_job = shafts(planner)
    with pytest.raises(VoucherError, match="is draft: costs go to a released or completed order"):
        services.code_lines(accountant, voucher, [CodingInput(1, job_ref=draft_job.number)])
    services.code_lines(
        accountant,
        voucher,
        [
            CodingInput(
                1, division=Division.objects.get(code="WS"), job_ref=f" {job.number.lower()} "
            )
        ],
    )
    coded = voucher.lines.get()
    assert (coded.job_id, coded.production_order_id, coded.job_ref) == (job.pk, None, job.number)
    # A supplier invoice line too.
    with pytest.raises(InvoiceError, match="Line 1: There is no job order"):
        invoices.create(
            clerk,
            supplier=supplier,
            division=Division.objects.get(code="IM"),
            invoice_no="INV-9",
            lines=[LineInput(grn_line.pk, "1000", "12.50", None, "MO99")],
        )
    bill = invoices.create(
        clerk,
        supplier=supplier,
        division=Division.objects.get(code="IM"),
        invoice_no="INV-9",
        lines=[LineInput(grn_line.pk, "1000", "12.50", None, job.number)],
    )
    assert bill.lines.get().job_id == job.pk
    shown = as_user(clerk).get(f"/api/v1/supplier-invoices/{bill.pk}/").json()
    assert shown["lines"][0]["order"] == job.number
    seen = jobs.payload(job, planner)["bills"]
    assert sorted((b["kind"], b["number"]) for b in seen) == [
        ("invoice", bill.number),
        ("voucher", voucher.number),
    ]


def test_production_orders_take_costs_too(planner, shaft):  # noqa: F811
    with pytest.raises(OrderNotFound, match="There is no job order or production order MO1"):
        order_for("MO1")
    assert order_for("  ") == (None, None, "")
