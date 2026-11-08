"""Demo data for trying the ERP (backlog P1-12, P15-12, P16-14): loads through the normal
services, never on production, each part once only."""

import io
import re
from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.core import crypto
from apps.core.models import User
from apps.inventory.models import (
    GoodsReceipt,
    IncomingInspection,
    InspectionPlan,
    Item,
    OpeningStock,
)
from apps.masters.models import Customer, Machine, Section
from apps.payments.models import SupplierPayment
from apps.payroll.models import Employee
from apps.production import plan, rates
from apps.production.models import Bom, PlanEntry, ProductionOrder
from apps.purchasing import reports
from apps.purchasing.models import PurchaseOrder, SupplierInvoice
from apps.sales.models import CustomerAdvance, Quotation, SalesOrder
from apps.vouchers.management.commands import load_demo_data
from apps.vouchers.models import Voucher

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


def test_demo_data_covers_every_stage(settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    out = io.StringIO()
    call_command("load_demo_data", stdout=out)
    text = out.getvalue()

    people = User.objects.filter(email__endswith="@demo.sml.lk")
    assert sorted(people.values_list("email", flat=True)) == [
        "accountant@demo.sml.lk",
        "cashier@demo.sml.lk",
        "clerk@demo.sml.lk",
        "director@demo.sml.lk",
        "hr@demo.sml.lk",
        "planner@demo.sml.lk",
        "productionmanager@demo.sml.lk",
        "purchasing@demo.sml.lk",
        "qc@demo.sml.lk",
        "sales@demo.sml.lk",
        "salesmanager@demo.sml.lk",
        "stores@demo.sml.lk",
        "supervisor@demo.sml.lk",
    ]
    secret = re.search(r"Key: ([A-Z2-7]{32})", text).group(1)
    assert {crypto.decrypt(u.totp_secret_encrypted) for u in people} == {secret}
    assert all(u.check_password("Demo-SML-2026!") for u in people)

    statuses = sorted(Voucher.objects.values_list("status", flat=True))
    assert statuses == sorted(
        [
            "draft",
            "submitted",
            "submitted",
            "returned",
            "accountant_approved",
            "director_approved",
            "partly_paid",
            "paid",
        ]
    )
    assert SupplierPayment.objects.count() == 2
    assert all(v.attachments.exists() for v in Voucher.objects.exclude(status="draft"))
    # Sales (P15-12): quotations at every stage, an open order and an advance.
    assert sorted(Quotation.objects.values_list("status", flat=True)) == [
        "accepted",
        "awaiting_approval",
        "draft",
        "lost",
        "sent",
    ]
    order = SalesOrder.objects.get()
    assert (order.status, order.customer_po) == ("open", "UL/PO/7781")
    assert order.lines.get().schedule.count() == 3
    assert CustomerAdvance.objects.get().status == "approved"
    assert Customer.objects.count() == 3
    # Purchasing (P16-14): POs at every stage, a GRN waiting for QC, a posted and a held invoice.
    assert sorted(Item.objects.values_list("code", flat=True)) == [
        "BAG-1K",
        "CAP-38",
        "CNMG-120408",
        "EN8-40",
        "M8-INSERT",
        "MB-WHT",
        "PP-H-25",
    ]
    assert InspectionPlan.objects.get().parameters.count() == 2
    assert sorted(PurchaseOrder.objects.values_list("status", flat=True)) == [
        "awaiting_approval",
        "draft",
        "partly_received",
        "received",
        "received",
    ]
    assert GoodsReceipt.objects.filter(status="confirmed").count() == 3
    waiting = GoodsReceipt.objects.get(lines__inspection__isnull=True)
    assert waiting.lines.get().packages.count() == 10
    assert sorted(IncomingInspection.objects.values_list("accepted_quantity", flat=True)) == [
        500,
        4800,
    ]
    assert sorted(SupplierInvoice.objects.values_list("invoice_no", "status")) == [
        ("PRL-2301", "posted"),
        ("PTL-7702", "held"),
    ]
    director = people.get(email="director@demo.sml.lk")
    assert reports.grni_ledger_balance() == "60000.00"  # 4,800 inserts at 12.50, held
    assert len(reports.held_invoices(director)) == 1
    # Production (P3): staff on a roster, presses, mould, approved BOM, stock, rates, orders
    # and today's plan, ready for the Supervisor's shift report.
    supervisor = people.get(email="supervisor@demo.sml.lk")
    section = Section.objects.get(code="IM-MLD")
    assert list(section.supervisors.all()) == [supervisor]
    assert Employee.objects.filter(section=section).count() == 4
    presses = set(Machine.objects.filter(section=section).values_list("code", flat=True))
    assert {"IMM-150", "IMM-250"} <= presses
    bom = Bom.objects.get(item__code="CAP-38")
    assert (bom.status, bom.mould.code) == ("approved", "MD-C38")
    assert sorted(ProductionOrder.objects.values_list("status", "purpose")) == [
        ("draft", "stock"),
        ("released", "sales"),
    ]
    released = ProductionOrder.objects.get(status="released")
    assert released.bom_lines.count() == 3 and released.dues.get().quantity == 20000
    today = timezone.localdate()
    assert PlanEntry.objects.filter(day=today, order=released).count() == 1
    assert rates.labour_on(section) == Decimal("450")
    assert OpeningStock.objects.get().status == "posted"
    assert plan.board(people.get(email="planner@demo.sml.lk"), today.isoformat(), 1)["entries"]
    assert "supervisor@demo.sml.lk" in text
    with pytest.raises(CommandError, match="already loaded"):
        call_command("load_demo_data", stdout=io.StringIO())


def test_never_on_production(settings, monkeypatch):
    settings.DEBUG = False
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    with pytest.raises(CommandError, match="never production"):
        call_command("load_demo_data", stdout=io.StringIO())
    monkeypatch.delenv("APP_ENVIRONMENT")
    with pytest.raises(CommandError, match="never production"):
        call_command("load_demo_data", stdout=io.StringIO())
    assert not User.objects.filter(email__endswith="@demo.sml.lk").exists()


def test_a_pc_with_the_earlier_demo_gets_only_the_missing_part(settings, monkeypatch):
    """The owner's PC was loaded before purchasing existed: running the command again adds the
    purchasing part with the same password and authenticator entry, and nothing twice."""
    settings.DEBUG = True
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    monkeypatch.setattr(load_demo_data, "PARTS", ("vouchers", "sales"))
    call_command("load_demo_data", stdout=io.StringIO())
    assert not User.objects.filter(email="stores@demo.sml.lk").exists()
    assert not PurchaseOrder.objects.exists()
    vouchers = Voucher.objects.count()

    monkeypatch.undo()
    settings.DEBUG = True
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    out = io.StringIO()
    call_command("load_demo_data", stdout=out)
    assert "Demo data loaded: purchasing, production." in out.getvalue()
    assert Voucher.objects.count() == vouchers
    assert Customer.objects.count() == 3
    assert PurchaseOrder.objects.count() == 5
    secrets = {
        crypto.decrypt(u.totp_secret_encrypted)
        for u in User.objects.filter(email__endswith="@demo.sml.lk")
    }
    assert len(secrets) == 1
    assert User.objects.get(email="qc@demo.sml.lk").check_password("Demo-SML-2026!")
    with pytest.raises(CommandError, match="already loaded"):
        call_command("load_demo_data", stdout=io.StringIO())
