"""Mould making and inter-division transfers (backlog P3-15): a completed workshop job for a
moulding mould is transferred at cost (material issued less returned, supplier bills coded
to the job, labour and overhead for its approved job card time) by the Accountant: a repair
is charged to the moulding division, a new company mould is capitalised to its fixed asset;
Cr Inter-division sales in the workshop; repairs left out of the company total."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.models import Account
from apps.core.models import Division
from apps.masters.models import Section
from apps.production import jobs, moulds, shift_approval, shift_reports, transfers
from apps.production.models import CostRate, InterDivisionTransfer, Mould
from apps.production.transfers import TransferError
from apps.vouchers import services
from apps.vouchers.services import CodingInput

from .test_access import as_user, person
from .test_job_cards import line, open_report, save, supervisor  # noqa: F401
from .test_job_orders import accountant, give, manager, planner, shaft, storeman  # noqa: F401
from .test_shift_reports import clock  # noqa: F401
from .test_vouchers import attach, draft, payee

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()
BASE = {"cycle_time_s": "12", "shot_weight_g": "40", "runner_weight_g": "4"}


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def mould(planner, shaft):  # noqa: F811
    from apps.inventory.models import Item

    Item.objects.create(
        code="CAP-28", name="Cap", category="finished", unit="pcs", created_by=planner
    )  # noqa: E501
    return moulds.create(
        planner, BASE | {"code": "MD-001", "name": "Cap 28", "parts": "CAP-28 x 8"}
    )  # noqa: E501


def mould_job(planner, purpose="mould_repair", code="MD-001"):  # noqa: F811
    job = jobs.create(
        planner,
        {
            "purpose": purpose,
            "division": "WS",
            "mould": code,
            "description": "Repair cavity 3",
            "quantity": "1",
            "due_date": TODAY,
            "operations": [{"seq": 10, "name": "Weld and polish", "section": "M-LAT"}],
            "materials": [{"component": "EN8-50", "per_piece": "5"}],
        },
    )
    return jobs.release(planner, job)


@pytest.fixture
def costed(clock, planner, manager, accountant, director, storeman, supervisor, mould):  # noqa: F811
    """A repair of MD-001 (IM) in the workshop: 4 kg EN8 issued and 1 back at 108.00/kg, two
    hours on the lathe at 600 labour and 400 overhead an hour, a 25,000 bill coded to it."""
    job = mould_job(planner)
    issued = give(storeman, job, ("EN8-50", "4", ""))
    jobs.give_back(
        storeman,
        job,
        {"issue": issued.pk, "lines": [{"line": issued.lines.get().pk, "quantity": "1"}]},
    )  # noqa: E501
    lathe = Section.objects.get(code="M-LAT")
    for kind, rate in (("labour", "600"), ("overhead", "400")):
        CostRate.objects.create(
            kind=kind, section=lathe, rate=D(rate), effective_from=date(2026, 1, 1), reason="test"
        )  # noqa: E501
    report = open_report(supervisor, "M-LAT")
    save(supervisor, report, line(job, 10, completed="1", end_time="10:00", machine="M-LAT-01"))
    shift_reports.submit(supervisor, report)
    shift_approval.decide(manager, report, "approve")
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    voucher = draft(clerk, payee("Precision Welders"))
    attach(clerk, voucher)
    services.submit(clerk, voucher)
    services.code_lines(
        accountant,
        voucher,
        [
            CodingInput(
                1,
                account=Account.objects.get(number="6210"),
                division=Division.objects.get(code="WS"),
                job_ref=job.number,
            )
        ],  # noqa: E501
    )
    services.approve(accountant, voucher)
    services.approve(director, voucher)
    return job


def test_a_mould_repair_is_charged_to_moulding_at_cost(planner, accountant, costed):  # noqa: F811
    job = costed
    shown = as_user(accountant).get(f"/api/v1/job-orders/{job.pk}/").json()["transfer"]
    assert {
        k: shown[k] for k in ("material", "bills", "labour", "overhead", "amount", "hours")
    } == {  # noqa: E501
        "material": "324.00",
        "bills": "25000.00",
        "labour": "1200.00",
        "overhead": "800.00",
        "amount": "27324.00",
        "hours": "2.00",
    }
    assert (shown["can_post"], shown["why_not"]) == (
        False,
        f"{job.number} is transferred when it is completed.",
    )  # noqa: E501
    jobs.complete(planner, job)
    with pytest.raises(TransferError, match="The Accountant posts"):
        transfers.post(planner, job)
    posted = as_user(accountant).post(f"/api/v1/job-orders/{job.pk}/transfer/", {}, format="json")
    assert posted.status_code == 200, posted.json()
    done = InterDivisionTransfer.objects.get(job=job)
    assert (done.kind, done.from_division.code, done.to_division.code, done.amount) == (
        "repair",
        "WS",
        "IM",
        D("27324.00"),
    )
    lines = sorted(
        (x.account.system_role, x.division.code, x.debit, x.credit)
        for x in done.journal_entry.lines.all()  # noqa: E501
    )
    assert lines == [
        ("inter_division_charges", "IM", D("27324.00"), D("0")),
        ("inter_division_income", "WS", D("0"), D("27324.00")),
    ]
    with pytest.raises(TransferError, match="already transferred"):
        transfers.post(accountant, job)
    with pytest.raises(DatabaseError, match="never changed or deleted"), transaction.atomic():
        InterDivisionTransfer.objects.filter(pk=done.pk).update(notes="x")
    # Income in the workshop, a cost in moulding, neither in the company total.
    income = Account.objects.get(system_role="inter_division_income")
    charges = Account.objects.get(system_role="inter_division_charges")
    ws = journal.profit_and_loss(TODAY, TODAY, Division.objects.get(code="WS"))
    im = journal.profit_and_loss(TODAY, TODAY, Division.objects.get(code="IM"))
    company = journal.profit_and_loss(TODAY, TODAY)
    assert (ws.get(income.pk), im.get(charges.pk)) == (D("27324.00"), D("-27324.00"))
    assert company.get(income.pk, D("0")) == 0 and company.get(charges.pk, D("0")) == 0


def test_a_job_with_no_cost_is_not_transferred(planner, accountant, mould):  # noqa: F811
    job = mould_job(planner)
    jobs.complete(planner, job)
    with pytest.raises(TransferError, match="no cost yet"):
        transfers.post(accountant, job)


def test_new_mould_transfer_registers_the_asset(planner, accountant, storeman, mould):  # noqa: F811
    moulds.create(planner, BASE | {"code": "MD-002", "name": "Lid 90", "parts": "CAP-28 x 4"})
    job = mould_job(planner, "new_mould", "MD-002")
    give(storeman, job, ("EN8-50", "5", ""))  # 5 kg at 108.00
    jobs.complete(planner, job)
    done = transfers.post(accountant, job, "First mould made in house")
    m = Mould.objects.get(code="MD-002")
    assert (done.kind, done.amount, m.asset_id) == ("new_mould", D("540.00"), done.fixed_asset_id)
    asset = done.fixed_asset
    assert (asset.asset_class.code, asset.division.code, asset.cost) == (
        "MOULDS",
        "IM",
        D("540.00"),
    )  # noqa: E501
    assert asset.terms.get().status == "awaiting"  # its depreciation terms go to the Director
    debit = done.journal_entry.lines.get(debit__gt=0)
    assert (debit.account.number, debit.division.code) == ("1530", "IM")
    # The capitalised mould stays in the company total: it offsets the costs it was made of.
    income = Account.objects.get(system_role="inter_division_income")
    assert journal.profit_and_loss(TODAY, TODAY).get(income.pk) == D("540.00")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"purpose": "tools"}, "Only mould making and mould repair jobs"),
        ({"division": "IM"}, "belongs to the division that made it"),
        ({"owner": "customer"}, "a customer's mould"),
        ({"asset": True}, "already in the fixed asset register"),
    ],
)
def test_what_cannot_be_transferred(planner, accountant, storeman, mould, change, message):  # noqa: F811
    m = Mould.objects.get(code="MD-001")
    purpose = change.get("purpose", "new_mould")
    if purpose == "tools":
        job = jobs.release(
            planner,
            jobs.create(
                planner,
                {
                    "purpose": "tools",
                    "division": "WS",
                    "description": "Jig",
                    "quantity": "1",
                    "due_date": TODAY,
                    "operations": [{"seq": 10, "name": "Mill", "section": "M-LAT"}],
                },
            ),
        )
    else:
        job = mould_job(planner, purpose)
    if change.get("division"):
        Mould.objects.filter(pk=m.pk).update(division=Division.objects.get(code="WS"))
    if change.get("owner"):
        from apps.masters import customers

        sales = person("sales@sml.lk", "sales_executive", all_divisions=True)
        customer = customers.create_customer(sales, {"name": "Unilever Sri Lanka"})
        Mould.objects.filter(pk=m.pk).update(owner="customer", customer=customer)
    if change.get("asset"):
        from apps.assets import services as assets
        from apps.assets.models import AssetClass

        asset = assets.register(
            accountant,
            asset_class=AssetClass.objects.get(code="MOULDS"),
            division=Division.objects.get(code="IM"),
            name="MD-001 Cap 28",
            acquisition_date=TODAY,
            cost="100000",
        )
        Mould.objects.filter(pk=m.pk).update(asset=asset)
    jobs.complete(planner, job)
    job.refresh_from_db()
    assert message in transfers.why_not(job)
