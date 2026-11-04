# ruff: noqa: F811 - the fixtures of test_export_invoices are imported and used by name
"""The VAT return shows exports apart, as zero-rated supplies (backlog P2-20)."""

from decimal import Decimal

import pytest

from apps.accounting import tax_reports

from .test_export_invoices import (  # noqa: F401 - fixtures used by name
    INVOICED,
    accountant,
    buyer,
    director,
    executive,
    invoice,
    order,
    setup,
    stores,
)

pytestmark = pytest.mark.django_db


def test_an_export_is_a_zero_rated_supply_in_lkr(invoice):
    data = tax_reports.vat_return(INVOICED.year, INVOICED.month)
    assert data["supplies"]["zero"] == Decimal("750000.00")  # USD 2,500.00 at 300.00
    assert data["supplies"]["standard"] == Decimal("0")
    assert data["output_vat"] == Decimal("0")
