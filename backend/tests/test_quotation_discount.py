"""A discount on quotations (owner, 31 Oct 2026; backlog P15-07b)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode, TaxComponent
from apps.core.models import Division
from apps.masters import costing_rates, customers
from apps.sales import costing, printing, services, workflow
from apps.sales.costing import CostingInput, ExtraInput
from apps.sales.models import Quotation
from apps.sales.services import LineInput, SalesError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def rhino(executive):
    return customers.create_customer(executive, {"name": "Rhino Roofing Products Ltd"})


@pytest.fixture
def vat_sscl(accountant):
    start = TODAY - timedelta(days=30)
    for code, rate in (("VAT", "18"), ("SSCL", "2.5")):
        taxes.add_rate(
            accountant, TaxComponent.objects.get(code=code), effective_from=start, rate=rate
        )
    return TaxCode.objects.get(code="VAT-SSCL")


def mould(user, customer, tax_code=None, **values):
    """The owner's proforma sample: a 32-cavity mould at LKR 550,000 less 3%."""
    return services.save(
        user,
        None,
        customer=customer,
        division=Division.objects.get(code="IM"),
        lines=[
            LineInput(
                description='Plastic injection mould for "CLIP", 32 cavities, P20',
                quantity="1",
                unit_price="550000",
                tax_code=tax_code,
                is_tooling=True,
            )
        ],
        **values,
    )


def test_the_discount_comes_off_before_the_taxes(executive, rhino, vat_sscl):
    q = mould(executive, rhino, vat_sscl, discount_pct="3")
    line = q.lines.get()
    assert (line.amount, line.discount, line.net) == (
        Decimal("550000.00"),
        Decimal("16500.00"),
        Decimal("533500.00"),
    )
    # SSCL 2.5% on 533,500 = 13,337.50; VAT 18% on 546,837.50 = 98,430.75
    assert line.tax_amount == Decimal("111768.25")
    assert (q.discount_pct, q.discount_total, q.subtotal) == (
        Decimal("3.00"),
        Decimal("16500.00"),
        Decimal("533500.00"),
    )
    assert q.total_amount == q.total_lkr == Decimal("645268.25")


def test_no_discount_by_default_and_it_can_be_removed(executive, rhino):
    q = mould(executive, rhino)
    assert (q.discount_pct, q.discount_total, q.subtotal) == (0, 0, Decimal("550000.00"))
    first = q.lines.get()
    line = LineInput(id=first.id, description="Mould", quantity="1", unit_price="550000")
    q = services.save(executive, q, lines=[line], discount_pct="5")
    assert q.subtotal == Decimal("522500.00")
    q = services.save(executive, q, lines=[line], discount_pct="")
    assert q.discount_total == 0 and q.subtotal == Decimal("550000.00")


@pytest.mark.parametrize(
    "pct, why",
    [("100", "below 100%"), ("-1", "cannot be negative"), ("2.125", "2 decimal places")],
)
def test_a_wrong_discount_is_refused(executive, rhino, pct, why):
    with pytest.raises(SalesError, match=why):
        mould(executive, rhino, discount_pct=pct)


def test_the_margin_is_on_the_price_after_the_discount(executive, rhino, accountant):
    costing_rates.add_costing_rate(
        accountant,
        Division.objects.get(code="IM"),
        effective_from=TODAY,
        overhead_pct="15",
        margin_pct="20",
        setup_rate="1000",
    )
    q = services.save(
        executive,
        None,
        customer=rhino,
        division=Division.objects.get(code="IM"),
        discount_pct="3",
        lines=[LineInput(description="Bracket", quantity="10", unit_price="1500")],
    )
    costing.save(
        executive,
        q,
        1,
        CostingInput(method="machining", extras=[ExtraInput("Bought in", "1000")]),
    )
    line = q.lines.get()
    (row,) = costing.results(line.costing, line, q.exchange_rate)
    assert row["cost"] == Decimal("1150.00")
    assert row["quoted_price"] == Decimal("1455.00")  # 1,500 less 3%
    assert row["quoted_margin_pct"] == Decimal("26.52")


def test_the_printed_quotation_shows_the_discount_line(executive, rhino, vat_sscl):
    q = mould(executive, rhino, vat_sscl, discount_pct="3")
    pdf = printing.render(Quotation.objects.get(pk=q.pk), compress=False)
    assert b"Discount" in pdf
    assert b"-16,500.00" in pdf
    assert b"546,837.50" in pdf  # subtotal: 533,500 + SSCL 13,337.50
    assert b"645,268.25" in pdf


def test_a_revision_keeps_the_discount_and_an_approved_one_never_changes(
    executive, director, rhino
):
    q = mould(executive, rhino, discount_pct="3")
    workflow.submit(executive, q)
    q = workflow.approve(director, q)
    with pytest.raises(DatabaseError, match="make a revision"), transaction.atomic():
        Quotation.objects.filter(pk=q.pk).update(discount_pct=Decimal("10"))
    new = workflow.revise(executive, q)
    assert (new.discount_pct, new.discount_total) == (Decimal("3.00"), Decimal("16500.00"))


def test_the_api_takes_and_shows_the_discount(executive, rhino):
    client = as_user(executive)
    made = client.post(
        "/api/v1/quotations/",
        {
            "customer": rhino.pk,
            "division": "IM",
            "discount_pct": "3",
            "lines": [{"description": "Mould", "quantity": "1", "unit_price": "550000"}],
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    body = made.json()
    assert (body["discount_pct"], body["discount_total"], body["subtotal"]) == (
        "3.00",
        "16500.00",
        "533500.00",
    )
    assert body["lines"][0]["discount"] == "16500.00"
