# ruff: noqa: F811 - fixtures of other test modules are imported and used by name
"""Parallel run: the ERP against QuickBooks for the same date (backlog P2-29)."""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounting import parallel

from .test_access import as_user, person
from .test_journal import acc, accountant, director  # noqa: F401
from .test_quickbooks_migration import (  # noqa: F401
    masters,
    payables,
    posted,
    receivables,
    role,
    trial_balance,
)

pytestmark = pytest.mark.django_db


def by_label(rows):
    return {r["label"]: r for r in rows}


def test_after_the_opening_balances_the_balance_sheet_agrees(posted):
    result = parallel.compare(
        trial_balance=trial_balance(), receivables=receivables(), payables=payables()
    )
    rows = by_label(result["accounts"])
    cash = rows[f"1010 {acc('1010').name}".strip()]
    assert (cash["quickbooks"], cash["erp"], cash["agrees"]) == ("500000.00", "500000.00", True)
    ar = role("accounts_receivable")
    assert rows[f"{ar.number} {ar.name}".strip()]["agrees"] is True
    # QuickBooks still shows the year's sales; the ERP carried them to retained earnings.
    sales = rows[f"4010 {acc('4010').name}"]
    assert (sales["quickbooks"], sales["erp"], sales["difference"]) == (
        "-900000.00",
        "0.00",
        "900000.00",
    )
    assert result["accounts"][0]["agrees"] is False  # differences come first
    assert result["customers"]["rows"] == [
        {
            "label": "Lanka Tiles PLC",
            "quickbooks": "150000.00",
            "erp": "150000.00",
            "difference": "0.00",
            "agrees": True,
        }
    ]
    assert result["suppliers"]["rows"][0]["agrees"] is True
    assert result["differences"]["customers"] == 0


def test_the_screens_api(accountant, posted):
    api = as_user(accountant)
    got = api.post(
        "/api/v1/parallel-run/",
        {"trial_balance": SimpleUploadedFile("tb.xlsx", trial_balance(cash="499000"))},
        format="multipart",
    )
    assert got.status_code == 200, got.json()
    cash = next(r for r in got.json()["accounts"] if r["label"].startswith("1010 "))
    assert Decimal(cash["difference"]) == Decimal("1000.00")
    assert got.json()["customers"] is None
    clerk = as_user(person("clerk@sml.lk", "clerk", all_divisions=True))
    assert clerk.post("/api/v1/parallel-run/", {}, format="multipart").status_code == 403
